#!/usr/bin/python3

# SPDX-License-Identifier: MIT

import click
import koji
import logging
import os
import sys

from get_distro_packages import get_distro_packages


logger = logging.getLogger(os.path.basename(__file__))


# to prevent an unfortunate situation, if the ratio of undesired builds to
# the current total number of builds in the given tag exceeds FORCE_THRESHOLD,
# then the --force option must be supplied to complete the untagging operation
FORCE_THRESHOLD = 0.5


def get_undesired_builds(session, koji_tag, desired_pkgs, force):
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
    num_current_builds = len(builds)

    # if no current builds, none are undesired so return empty set
    if num_current_builds == 0:
        return undesired_builds

    for binfo in builds:
        pkg = binfo["package_name"]
        nvr = binfo["nvr"]

        logger.debug("Found build of package {} with nvr {}".format(pkg, nvr))

        if pkg not in desired_pkgs:
            logger.debug("PACKAGE BUILD {} NEEDS TO BE REMOVED FROM TAG".format(nvr))

            undesired_builds.add(nvr)

    num_undesired_builds = len(undesired_builds)
    undesired_ratio = num_undesired_builds / num_current_builds

    print(
        "Koji tag {} currently has {} builds, {} ({:.2%}) of which are undesired".format(
            koji_tag,
            num_current_builds,
            num_undesired_builds,
            undesired_ratio
        )
    )

    if undesired_ratio > FORCE_THRESHOLD:
        print(
            "WARNING: Undesired build ratio is above safety threshold"
            " ({:.2%})".format(FORCE_THRESHOLD)
        )
        if force:
            print("--force option has been set. Proceeding.")
        else:
            print(
                "Use --force option if you wish to proceed despite this warning.",
                file=sys.stderr
            )
            return None

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
    with session.multicall() as m:
        for nvr in sorted(builds):
            if dry_run:
                print("Would have untagged {}".format(nvr))
            else:
                print("Untagging {}".format(nvr))
                m.untagBuild(koji_tag, nvr)


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
              default="prototype-eln-and-buildroot")
@click.option("--arches", "--arch",
              multiple=True,
              help="The architectures to include",
              show_default=True,
              default=["aarch64", "armv7hl", "ppc64le", "s390x", "x86_64"])
@click.option("--force",
              is_flag=True,
              help=(
                  "Force untagging even if removal ratio exceeds"
                  " threshold ({:.2%})").format(FORCE_THRESHOLD),
              show_default=True,
              default=False)
def cli(dry_run, debug, koji_url, koji_tag, distro_url, distro_view, arches, force):
    """
    Automated removal of packages from koji tag that have been trimmed from
    distribution.
    """
    if debug:
        logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
        logger.setLevel(logging.DEBUG)
        logger.debug("Debugging mode enabled")
    else:
        logging.basicConfig()

    session = koji.ClientSession(koji_url)
    try:
        session.gssapi_login()
    except:
        print("ERROR: an authentication error has occurred", file=sys.stderr)
    if not session.logged_in:
        print(
            "Unable to log in to Koji."
            " Did you forget to run 'kinit fasname@FEDORAPROJECT.ORG'?",
            file=sys.stderr
        )
        return

    print(
        "Downloading and merging desired {distro_view} sources"
        " for arches: {arches}".format(
            distro_view=distro_view, arches=", ".join(arches)
        )
    )
    desired_pkgs = get_distro_packages(distro_url, distro_view, arches, logger=logger)

    builds_to_untag = get_undesired_builds(session, koji_tag, desired_pkgs, force)
    if not builds_to_untag:
        print("No builds to untag")
        return

    logger.debug("Builds to untag: {}".format(builds_to_untag))

    untag_builds(session, koji_tag, dry_run, builds_to_untag)


if __name__ == "__main__":
    cli()
