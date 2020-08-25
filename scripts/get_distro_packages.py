# SPDX-License-Identifier: MIT

import logging
import os
import requests
import sys


def get_distro_packages(distro_url, distro_view, arches, logger=None):
    """
    Fetches the list of desired sources for 'distro-view' from 'distro-url'
    for each of the given 'arches'.

    :param distro_url: top level of the content resolver
    :type distro_url: str
    :param distro_view: content resolver view
    :type distro_view: str
    :param arches: architectures to include
    :type arches: iterable
    :param logger: logger instance for debug output
    :type logger: logging.Logger
    :return: list of packages that are desired, merged for all 'arches'
    :rtype: set

    """
    merged_packages = set()

    for arch in arches:
        url = (
            "{distro_url}"
            "/view-source-package-name-list--view-{distro_view}--{arch}.txt"
        ).format(distro_url=distro_url, distro_view=distro_view, arch=arch)

        if logger:
            logger.debug("downloading {url}".format(url=url))

        r = requests.get(url, allow_redirects=True)
        for line in r.text.splitlines():
            merged_packages.add(line)

    if logger:
        logger.debug("Found a total of {} packages".format(len(merged_packages)))

    return merged_packages


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
    logger = logging.getLogger(os.path.basename(__file__))
    logger.setLevel(logging.DEBUG)
    logger.debug("Debugging mode enabled")

    distro_url = "https://tiny.distro.builders"
    distro_view = "prototype-eln-and-buildroot"
    arches = ["aarch64", "armv7hl", "ppc64le", "s390x", "x86_64"]

    if len(sys.argv) == 2 and sys.argv[1] == "--help":
        print("Usage: {} [ distro-view [ distro-url [ 'arches' ] ] ]".format(sys.argv[0]))
        print("  distro-view  The content resolver view"
              "  [default: {}]".format(distro_view))
        print("  distro-url   The top level of the content resolver"
              "  [default: {}]".format(distro_url))
        print("  arches       The architectures to include"
              "  [default: '{}']".format(" ".join(arches)))
        sys.exit()

    if len(sys.argv) > 1:
        distro_view = sys.argv[1]
    if len(sys.argv) > 2:
        distro_url = sys.argv[2]
    if len(sys.argv) > 3:
        arches = sys.argv[3].split()

    pkgs = get_distro_packages(distro_url, distro_view, arches, logger)

    for pkg in sorted(pkgs):
        print(pkg)
