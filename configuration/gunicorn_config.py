def add_build(worker):
    import logging
    import ipaddress
    from random import choice
    from datetime import datetime, timezone, timedelta
    from django.conf.urls import url
    from django.http import HttpResponse, Http404
    from django.views.generic import View
    from django.shortcuts import get_list_or_404
    from django.template.loader import get_template
    from django.contrib.contenttypes.models import ContentType
    from django.contrib.auth.models import Permission, Group, User
    from users.models import Token
    from ipam.models import IPAddress, Prefix
    from dcim.models import Device
    from virtualization.models import VirtualMachine
    from dcim.urls import urlpatterns
    from extras.models import CustomFieldValue

    logger = logging.getLogger("netbox")

    IPA_ENABLED = False
    try:
        from python_freeipa import ClientMeta as IPAClient
        from python_freeipa import exceptions as ipa_exceptions
        logger.info("IPA support is ENABLED.")
        IPA_ENABLED = True
    except ImportError as ex:
        logger.info("IPA support is DISABLED: %s", str(ex))


    def _create_ipa_host(device):
        if not IPA_ENABLED:
            return None

        ipa_servers = device.get_config_context().get('ipa_servers', [])
        if not ipa_servers:
            return None

        ipa = IPAClient(choice(ipa_servers), verify_ssl=False)
        try:
            ipa.login_kerberos()
        except ipa_exceptions.Unauthorized as ex:
            logger.error("Unable to login to IPA: %s", str(ex))
            raise Http404()

        if ipa.host_find(o_fqdn=device.name).get("result", None):
            try:
                ipa.host_del(a_fqdn=device.name, o_updatedns=True)
            except Exception as ex:
                logger.error("failed to delete existing host entry: %s", str(ex))

        host_extra_attrs = {}
        if device.site:
            host_extra_attrs["o_nshostlocation"] = device.site.name

        try:
            host = ipa.host_add(
                a_fqdn=device.name,
                o_nsosversion=device.platform.name,
                o_ip_address=str(device.primary_ip4.address.ip),
                o_force=True,
                o_random=True,
                **host_extra_attrs,
            )["result"]
            logger.info('Created IPA host %s', device.name)
            return host['randompassword']

        except (ipa_exceptions.UnknownOption, ipa_exceptions.ValidationError) as ex:
            logger.error("IPA reported invalid API usage: %s", str(ex))
        except ipa_exceptions.DuplicateEntry as ex:
            logger.error("IPA reported that the host already exists - should not happen: %s", str(ex))

        raise Http404()


    def _create_network(interface, ip=None, vlan=None):
        members = [member.name for member in interface.member_interfaces.all()]
        if vlan:
            members = []

        network = dict(
            interface=interface.name,
            member_interfaces=members,
            vlan=vlan,
            ipaddress=None,
            netmask=None,
            gateway=None,
            primary=False,
        )

        if ip:
            gateway = IPAddress.objects.filter(
                address__net_contained_or_equal=ip.address.cidr,
                address__net_mask_length=ip.address.prefixlen,
                tags__name__in=["Gateway"]
            ).first()
            network["ipaddress"] = ipaddress.IPv4Interface(ip.address).with_netmask.split("/")[0]
            network["netmask"] = ipaddress.IPv4Interface(ip.address).with_netmask.split('/')[1]
            network["gateway"] = str(gateway.address.ip) if gateway else None
            network["primary"] = ip.address == interface.parent.primary_ip4.address

        return network


    def _networks_for_interface(interface):
        """Extrapolate OS network connections from interface."""
        untagged_vlan = interface.untagged_vlan.vid if interface.untagged_vlan else None
        untagged_vlan_ip = None
        tagged_vlan_ip = {i.vid: None for i in interface.tagged_vlans.all()}

        ipaddresses = list(interface.ip_addresses.all())
        if not(untagged_vlan or tagged_vlan_ip):
            # If there are no configured vlans
            # assume that the interface is not tagged and that any IP
            # is for the bare interface.
            ip = ipaddresses[0] if ipaddresses else None
            return [_create_network(interface, ip)]

        for ip in ipaddresses:
            # Sort ipaddresses into their vlans.
            prefix = Prefix.objects.filter(
                vrf=ip.vrf,
                prefix__net_contains=ip.address.ip,
                prefix__net_mask_length=ip.address.prefixlen,
            ).first()
            if not prefix:
                logger.warning("No prefix identified for IP: %s", ip.address.cidr)
                continue

            if prefix.vlan and prefix.vlan.vid in tagged_vlan_ip:
                tagged_vlan_ip[prefix.vlan.vid] = ip
            elif untagged_vlan and prefix.vlan and prefix.vlan.vid == untagged_vlan:
                untagged_vlan_ip = ip

        networks = [_create_network(interface, untagged_vlan_ip)]
        for vlan, ip in tagged_vlan_ip.items():
            networks.append(_create_network(interface, ip, vlan))

        return networks


    class BuildView(View):
        ''' Presents a build file e.g. a kickstart file '''

        def get(self, request):
            interface, device = None, None

            buildip = request.GET.get('ipaddr', None) or \
                    request.META.get('HTTP_X_REAL_IP', None) or \
                    request.META['REMOTE_ADDR']

            complete = request.GET.get('complete', None)

            device = Device.objects.filter(
                primary_ip4__address__startswith=buildip+'/'
            ).first() or VirtualMachine.objects.filter(
                primary_ip4__address__startswith=buildip+'/'
            ).first()

            if not device:
                logger.warning('dcim/build called with IP %s that is not associated with a device.', buildip)
                raise Http404('This IP is not associated with a buildable device')

            if not device.cf.get('redeploy', False):
                logger.warning("dcim/build called for %s which is not set to redeploy", device.name)
                raise Http404("Device not set to deploy")

            if not device.platform:
                logger.warning('dcim/build called with IP associated with device with no platform: IP: %s, device: %s', buildip, device.name)
                raise Http404('This device does not have a platform')

            networks = []
            member_interfaces = []
            for _i in device.interfaces.all():
                if _i.mgmt_only:
                    continue

                for network in _networks_for_interface(_i):
                    member_interfaces.extend(network["member_interfaces"])
                    networks.append(network)

            networks = [n for n in networks if n["interface"] not in member_interfaces]
            networks.sort(key=lambda ip: ip['primary'], reverse=True)

            user = User.objects.filter(username="deployment_user").first()
            token = None
            if user:
                token = Token.objects.create(user=user, expires=datetime.now(timezone.utc) + timedelta(minutes=30))
                token.save()

            try:
                template = get_template('build_templates/' + device.platform.slug)
                context = dict(
                    device=device,
                    networks=networks,
                    domain=device.name.split('.', 1)[-1],
                    otp=_create_ipa_host(device),
                    token=token.key if token else None,
                    request=request,
                )

                return HttpResponse(template.render(context), content_type='application/text')
            except Exception as exc:
                logger.error(exc, exc_info=True)
                raise Http404('This device is not buildable')

    urlpatterns.append(url(r'build/', BuildView.as_view(), name='build'))

command = '/usr/bin/gunicorn'
pythonpath = '/opt/netbox/netbox'
bind = '0.0.0.0:8001'
workers = 3
errorlog = '-'
accesslog = '-'
capture_output = False
loglevel = 'debug'
post_worker_init = add_build

