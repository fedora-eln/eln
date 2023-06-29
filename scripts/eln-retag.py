#!/usr/bin/python3

import argparse
import json
import koji
import logging
import os
import re
import rpm
import sys

from concurrent.futures import ThreadPoolExecutor, as_completed


logger = logging.getLogger(__name__)


def check_retag(session, nvr, tag, dry_run=False):
    buildinfo = session.getBuild(nvr)
    logger.debug(f"Package name: {buildinfo['name']}")

    # Look up latest tagged ENVR for this package
    latest_tagged = session.listTagged(tag, latest=True, package=buildinfo["name"])

    if len(latest_tagged) < 1 or compare_with_disttag(latest_tagged[0]["nvr"], nvr) < 0:
        # Tag this NVR
        return True

    # Do not tag this NVR
    return False

def compare_with_disttag(tagged_nvr, proposed_nvr):
    # First compare versions without the trailing dist tag
    split_tagged_nvr = tagged_nvr.rsplit(".", maxsplit=1)
    split_proposed_nvr = proposed_nvr.rsplit(".", maxsplit=1)
    res = rpm.labelCompare(split_tagged_nvr[0], split_proposed_nvr[0])
    if res < 0:
        # proposed_nvr is unambiguously higher
        return -1
    elif res > 0:
        # proposed_nvr is unambiguously lower
        return 1

    # Otherwise they are the same base version. Check for the disttag
    if split_tagged_nvr[1].startswith("eln"):
        # The existing tagged build is the ELN build. Do nothing.
        return 0

    # It's either the Fedora package or has no disttag. In either case,
    return -1


def parse_args():
    ap = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    ap.add_argument(
        "-l",
        "--loglevel",
        dest="loglevel",
        help="logging level",
        default="INFO",
    )

    ap.add_argument(
        "-t",
        "--tag",
        dest="tag",
        help="Koji tag",
        default="eln",
    )

    ap.add_argument(
        "-k",
        "--kojihub",
        dest="kojihub",
        help="Koji Hub URL",
        default="https://koji.fedoraproject.org/kojihub",
    )

    ap.add_argument(
        "-f",
        "--retag-file",
        dest="retagfile",
        help="A file containing a list of SRPM names to retag, if needed",
        default="retag.txt",
    )

    ap.add_argument(
        "--dry-run",
        dest="dry_run",
        help="Don't actually issue the tagging request",
        action="store_true",
        default=False
    )

    args = ap.parse_args()

    loglevel = getattr(logging, args.loglevel.upper())
    if not isinstance(loglevel, int):
        print("Invalid loglevel: {}".format(args.loglevel))
        sys.exit(1)

    return args


def main():
    logging.basicConfig(format="%(asctime)s : %(levelname)s : %(message)s")
    args = parse_args()
    loglevel = getattr(logging, args.loglevel.upper())
    logger.setLevel(loglevel)

    spkg_list = {}

    with open(args.retagfile) as retagfile:
        retag_nvrs = retagfile.read().splitlines()

    session = koji.ClientSession(args.kojihub)
    latest_builds = session.listTagged(args.tag, latest=True)

    logger.info(f"Builds in tag: {len(latest_builds)}")

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_nvr = dict()

        for nvr in retag_nvrs:
            future = executor.submit(check_retag, session, nvr, args.tag, args.dry_run)
            future_to_nvr[future] = nvr

        with session.multicall(batch=500) as mc:
            for future in as_completed(future_to_nvr):
                nvr = future_to_nvr[future]
                if future.result():
                    logger.info(f"Will tag {nvr} into {args.tag}")
                    if not args.dry_run:
                        mc.tagBuild()


if __name__ == "__main__":
    main()
