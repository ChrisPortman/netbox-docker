# Deployment Branch

This section documents the additional functionality of the deployment branch.  The original README is below.

## Overview

This branch adds funtionallity and configuration to a Netbox Docker deployment to support the automated install of
operating systems on Devices and Virtual Machines.  To do so, it provides:

* An additional view at `/dcim/build` which uses the request's source IP or the `ipaddr` query parameter to identify
the device from which the request originates.  Based on the device's configuration, an automated install (e.g. kickstart)
script is generated and provided as a response to the request.  This additional view is added to the Netbox application
via a gunicorn `post_worker_init` hook.
* Custom fields to support PyDHCP added via the initializers:
   * `redeploy` applies to device and virtual machine objects.  It is a boolean, that when made true, indicates the intent
to deploy/redeploy the device. This field is consulted by PyDHCP when determining whether or not to respond to a PXE boot request.
It is also required to be true for the `/dcim/build` view to produce an install script.
   * `confirm_redeploy` applies to device and virtual machine objects.  Performing a redeploy, particularly against a live device,
is obviously a very destructive action.  To protect against accidental redeployments, this field must be set to the `name` of the
device/virtual machine that is intended to tbe redeployed. This field is consulted by PyDHCP when determining whether or not to
respond to a PXE boot request.
   * `deploy_status` applies to device and virtual machine objects.  This field is available to be updated from the install process
to provide indicators of the deployment state of the device.
   * `pydhcp_mac` applies to IP Address objects.  This field is used by PyDHCP to track the MAC address to which a dynamic lease is
allocated.
   * `pydhcp_expire` applies to IP Address objects. This field is used by PyDHCP to track the expiry of a dynamic lease.
* A `deployment_user` user account with permissions only to change devices and virtual machines.  This user is created with no password and therefore
a random unknown password is generated.  This a token valid for 30 mins is created each time the `/dcim/build` view is called and generates
an install script.  The token is passed to the template and can be used to call back to netbox to update the build status during the build.

## Maintenance

Maintenance of this branch involves rebasing it against the upstream's **RELEASE** branch and running `docker-compose pull` to
refresh the netbox docker images.

## PyDHCP Integration

As above, this branch automatically provides the custom fields required to facilitate PyDHCP functionallity.  Strictly speaking,
you do not need to use PyDHCP to use the `/dcim/build` interface.

See more on PyDHCP here: https://github.com/ChrisPortman/pydchp

## Other Implications

* The `LOGIN_REQUIRED` option is required to be False.  The `/dcim/build` view needs to be accessable anonymously.  Leaving this
as false, does not appear to expose any actual data.  The home page will be viewable anonymously however the item counts will all
show the "lock" icon and no links to any other pages are available.  Browsing to URLs direct to objects will not work anonymously
either.  This indicates that the permission based access is still enforced.  Setting `LOGIN_REQURED` to true, appears to only have
the effect of redirecting any unauthenticated request to the login page.  It is this redirection that will break the `/dcim/build`
view.
* Once a device/virtual machine has its `redeploy` custom field set to true, the `/dcim/build` view will become available for it.
The build view supports specifying the IP address of the device using a query string `ipaddr=<IP ADDRESS>` to override the source
IP in the request.  This is helpful for debugging.  It also means however that the build script is available unauthenticated for
the duration of `redeploy` remaining true.  This has the potential for data leakage/reconnaissance.  For this reason, you should
ensure that `redeploy` is only True for as long as it is required to be.  Ideally the install scripts will have a callback that
sets it to false.  This is also required to avoid reinstall loops.

## Build Templates

The directory `build_templates` is where the templates rendered by the `/dcim/build` view are stored.  The template syntax is
Django's templating syntax.

When the `/dcim/build` receives a request, it identifes the relevant device or virtual machine based on the source IP address of the
request.  It then refers to the device's `platform` and loads the template from the `build_templates` directory with the file name
that matches the platform name's `slug` representation.

The template is redered with the following context:

```
{
    device=device,                 # Netbox Device model instance
    networks=[ networks_dicts ],   # List of dictionaries representing the devices network connections
    request=request,               # The request object
    token=token,                   # Token for the deployment_user that is valid for 30 mins
}
```

The network dicts represent a network configuration and are in the following format.  There will be one for each
IP address configured.  Interfaces named "ILO" will be ignored.

An example network dict:
```
dict(
    interface="bond0",
    ipaddress="10.1.1.100",
    netmask="255.255.0.0",
    member_interfaces=["eth0", "eth1"],
    gateway="10.1.1.1",
    primary=True,
    vlan="100",
)
```

There are example CentOS 7 kickstart templates included.  These templates depend on some config contexts that provide additional information:

**Deployment Repositories**

```json
{
    "deployment_repositories": {
        "base": "http://mirror.centos.org/centos/7/os/x86_64/",
        "epel": "http://mirror.internode.on.net/pub/epel/7/x86_64/",
        "updates": "http://mirror.internode.on.net/pub/centos/7/updates/x86_64/"
    }
}
```


## The PXE Process

Typically, your devices will PXE boot.  The file that it retrieves will need to appropriately link the process to the `/dcim/build` view.
This is an example `pxelinux.cfg/default` file located on a TFTP server that supports the automated build of a Centos 7 machine.

Note the `ks` kernel option:
```
default menu.c32
prompt 0
timeout 5

MENU TITLE Centos 7 PXE Boot
LABEL centos7_x64
MENU LABEL CentOS 7_X64
KERNEL vmlinuz
APPEND initrd=initrd.img ks=http://netbox.example.com/dcim/build/
```

# netbox-docker

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/netbox-community/netbox-docker)][github-release]
[![GitHub stars](https://img.shields.io/github/stars/netbox-community/netbox-docker)][github-stargazers]
![GitHub closed pull requests](https://img.shields.io/github/issues-pr-closed-raw/netbox-community/netbox-docker)
![Github release workflow](https://img.shields.io/github/workflow/status/netbox-community/netbox-docker/release)
![Docker Pulls](https://img.shields.io/docker/pulls/netboxcommunity/netbox)
[![MicroBadger Layers](https://img.shields.io/microbadger/layers/netboxcommunity/netbox)][netbox-docker-microbadger]
[![MicroBadger Size](https://img.shields.io/microbadger/image-size/netboxcommunity/netbox)][netbox-docker-microbadger]
[![GitHub license](https://img.shields.io/github/license/netbox-community/netbox-docker)][netbox-docker-license]

[The Github repository](netbox-docker-github) houses the components needed to build Netbox as a Docker container.
Images are built using this code and are released to [Docker Hub][netbox-dockerhub] once a day.

Do you have any questions?
Before opening an issue on Github, please join the [Network To Code][ntc-slack] Slack and ask for help in our [`#netbox-docker`][netbox-docker-slack] channel.

[github-stargazers]: https://github.com/netbox-community/netbox-docker/stargazers
[github-release]: https://github.com/netbox-community/netbox-docker/releases
[netbox-docker-microbadger]: https://microbadger.com/images/netboxcommunity/netbox
[netbox-dockerhub]: https://hub.docker.com/r/netboxcommunity/netbox/tags/
[netbox-docker-github]: https://github.com/netbox-community/netbox-docker/
[ntc-slack]: http://slack.networktocode.com/
[netbox-docker-slack]: https://slack.com/app_redirect?channel=netbox-docker&team=T09LQ7E9E
[netbox-docker-license]: https://github.com/netbox-community/netbox-docker/blob/release/LICENSE

## Docker Tags

* `vX.Y.Z`: These are release builds, automatically built from [the corresponding releases of Netbox][netbox-releases].
* `latest`: These are release builds, automatically built from [the `master` branch of Netbox][netbox-master].
* `snapshot`: These are pre-release builds, automatically built from the [`develop` branch of Netbox][netbox-develop].
* `develop-X.Y`: These are pre-release builds, automatically built from the corresponding [branch of Netbox][netbox-branches].

Then there is currently one extra tags for each of the above tags:

* `-ldap`: Contains additional dependencies and configurations for connecting Netbox to an LDAP directroy.
  [Learn more about that in our wiki][netbox-docker-ldap].

New images are built and published automatically every ~24h.

[netbox-releases]: https://github.com/netbox-community/netbox/releases
[netbox-master]: https://github.com/netbox-community/netbox/tree/master
[netbox-develop]: https://github.com/netbox-community/netbox/tree/develop
[netbox-branches]: https://github.com/netbox-community/netbox/branches
[netbox-docker-ldap]: https://github.com/netbox-community/netbox-docker/wiki/LDAP

## Quickstart

To get Netbox Docker up and running run the following commands.
There is a more complete [_Getting Started_ guide on our wiki][wiki-getting-started] which explains every step.

```bash
git clone -b release https://github.com/netbox-community/netbox-docker.git
cd netbox-docker
tee docker-compose.override.yml <<EOF
version: '3.4'
services:
  nginx:
    ports:
      - 8000:8080
EOF
docker-compose pull
docker-compose up
```

The whole application will be available after a few minutes.
Open the URL `http://0.0.0.0:8000/` in a web-browser.
You should see the Netbox homepage.
In the top-right corner you can login.
The default credentials are:

* Username: **admin**
* Password: **admin**
* API Token: **0123456789abcdef0123456789abcdef01234567**

[wiki-getting-started]: https://github.com/netbox-community/netbox-docker/wiki/Getting-Started
[docker-reception]: https://github.com/nxt-engineering/reception

## Documentation

Please refer [to our wiki on Github][netbox-docker-wiki] for further information on how to use this Netbox Docker image properly.
It covers advanced topics such as using secret files, deployment to Kubernetes as well as NAPALM and LDAP configuration.

[netbox-docker-wiki]: https://github.com/netbox-community/netbox-docker/wiki/

## Getting Help

Please join [our Slack channel `#netbox-docker`][netbox-docker-slack] on the [Network To Code Slack][ntc-slack].
It's free to use and there are almost always people online that can help.

If you need help with using Netbox or developing for it or against it's API you may find the `#netbox` channel on the same Slack instance very helpful.

## Dependencies

This project relies only on *Docker* and *docker-compose* meeting these requirements:

* The *Docker version* must be at least `17.05`.
* The *docker-compose version* must be at least `1.17.0`.

To check the version installed on your system run `docker --version` and `docker-compose --version`.

## Use a Specific Netbox Version

The `docker-compose.yml` file is prepared to run a specific version of Netbox, instead of `latest`.
To use this feature, set and export the environment-variable `VERSION` before launching `docker-compose`, as shown below.
`VERSION` may be set to the name of
[any tag of the `netboxcommunity/netbox` Docker image on Docker Hub][netbox-dockerhub].

```bash
export VERSION=v2.7.1
docker-compose pull netbox
docker-compose up -d
```

You can also build a specific version of the Netbox Docker image yourself.
`VERSION` can be any valid [git ref][git-ref] in that case.

```bash
export VERSION=v2.7.1
./build.sh $VERSION
docker-compose up -d
```

[git-ref]: https://git-scm.com/book/en/v2/Git-Internals-Git-References
[netbox-github]: https://github.com/netbox-community/netbox/releases

## Breaking Changes

From time to time it might become necessary to re-engineer the structure of this setup.
Things like the `docker-compose.yml` file or your Kubernetes or OpenShift configurations have to be adjusted as a consequence.

Since November 2019 each image built from this repo contains a `org.opencontainers.image.version` label.
(The images contained labels since April 2018, although in November 2019 the labels' names changed.)
You can check the label of your local image by running `docker inspect netboxcommunity/netbox:v2.7.1 --format "{{json .Config.Labels}}"`.

Please read [the release notes][releases] carefully when updating to a new image version.

[releases]: https://github.com/netbox-community/netbox-docker/releases

## Rebuilding the Image

`./build.sh` can be used to rebuild the Docker image. See `./build.sh --help` for more information.

For more details on custom builds [consult our wiki][netbox-docker-wiki-build].

[netbox-docker-wiki-build]: https://github.com/netbox-community/netbox-docker/wiki/Build

## Tests

We have a test script.
It runs Netbox's own unit tests and ensures that all initializers work:

```bash
IMAGE=netboxcommunity/netbox:latest ./test.sh
```

## About

This repository is currently maintained and funded by [nxt][nxt].

[nxt]: https://nxt.engineering/en/
