#!/usr/bin/python3

# SPDX-License-Identifier: MIT

import click
import koji
import requests


DEBUG = False


def get_desired_packages(distro_url, distro_view, arches):
    """
    Fetches the list of desired sources for 'distro-view' from 'distro-url'
    for each of the given 'arches'.

    :param distro_url: top level of the content resolver
    :type distro_url: str
    :param distro_view: content resolver view
    :type distro_view: str
    :param arches: architectures to include
    :type arches: tuple
    :return: list of packages that are desired, merged for all 'arches'
    :rtype: set

    """
    print(
        "Downloading and merging desired {distro_view} sources"
        " for arches: {arches}".format(
            distro_view=distro_view, arches=", ".join(arches)
        )
    )

    merged_builds = set()

    for arch in arches:
        url = (
            "{distro_url}"
            "/view-source-package-name-list--view-{distro_view}--{arch}.txt"
        ).format(distro_url=distro_url, distro_view=distro_view, arch=arch)

        if DEBUG:
            print("downloading {url}".format(url=url))

        r = requests.get(url, allow_redirects=True)
        for line in r.text.splitlines():
            merged_builds.add(line)

    return merged_builds


def get_undesired_builds(session, koji_tag, desired_pkgs):
    """
    Fetches the list of undesired builds currently tagged with
    'koji_tag'.

    :param session: Koji session
    :type session: koji.ClientSession
    :param koji_tag: Koji tag
    :type koji_tag: str
    :param desired_pkgs: list of packages to keep
    :type desired_pkgs: set
    :return: list of NVRs of builds that should be deleted from tag,
        or None if an error occurred
    :rtype: set
    """
    print(
        "Identifying undesirable builds in Koji tag {koji_tag}".format(
            koji_tag=koji_tag
        )
    )

    tag = session.getTag(koji_tag)
    if not tag:
        print("No such tag {}".format(koji_tag))
        return None

    undesired_builds = set()

    # get all builds with tag
    builds = session.listTagged(koji_tag)

    for binfo in builds:
        pkg = binfo["package_name"]
        nvr = binfo["nvr"]

        if DEBUG:
            print("Found build of package {} with nvr {}".format(pkg, nvr))

        if pkg not in desired_pkgs:
            if DEBUG:
                print("PACKAGE BUILD {} NEEDS TO BE REMOVED FROM TAG".format(nvr))

            undesired_builds.add(nvr)

    return undesired_builds


def untag_builds(session, koji_tag, dry_run, builds):
    """
    Untag given list of builds from 'koji_tag'.

    :param session: Koji session
    :type session: koji.ClientSession
    :param koji_tag: Koji tag
    :type koji_tag: str
    :param builds: list of builds to untag
    :type desired_pkgs: set
    """
    for nvr in sorted(builds):
        if dry_run:
            print("Would have untagged {}".format(nvr))
        else:
            print("Untagging {}".format(nvr))
            session.untagBuild(koji_tag, nvr)


@click.command()
@click.option("--debug",
              is_flag=True,
              help="Output a lot of debugging information",
              show_default=True,
              default=False)
@click.option("--dry-run",
              is_flag=True,
              help="Do a trial run without making any changes",
              show_default=True,
              default=False)
@click.option("--koji-url",
              help="The root of the Koji XMLRPC API",
              show_default=True,
              default="https://koji.fedoraproject.org/kojihub")
@click.option("--koji-tag",
              help="The Koji tag to trim",
              show_default=True,
              default="eln")
@click.option("--distro-url",
              help="The top level of the content resolver",
              show_default=True,
              default="https://tiny.distro.builders")
@click.option("--distro-view",
              help="The content resolver view",
              show_default=True,
              default="eln-and-buildroot")
@click.option("--arches", "--arch",
              multiple=True,
              help="The architectures to include",
              show_default=True,
              default=["aarch64", "armv7hl", "ppc64le", "s390x", "x86_64"])
def cli(dry_run, debug, koji_url, koji_tag, distro_url, distro_view, arches):
    """
    Automated removal of packages from koji tag that have been trimmed from
    distribution.
    """
    global DEBUG
    DEBUG = debug

    desired_pkgs = get_desired_packages(distro_url, distro_view, arches)

    session = koji.ClientSession(koji_url)

    builds_to_untag = get_undesired_builds(session, koji_tag, desired_pkgs)

    if DEBUG:
        print("Builds to untag: {}".format(builds_to_untag))

    untag_builds(session, koji_tag, dry_run, builds_to_untag)


if __name__ == "__main__":
    cli()
