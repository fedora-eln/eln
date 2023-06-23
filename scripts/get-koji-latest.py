#!/usr/bin/python3

import argparse
import json
import koji
import logging
import os
import re
import sys

from concurrent.futures import ThreadPoolExecutor, as_completed


logger = logging.getLogger(__name__)


def parse_args():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

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
        "--filter-file",
        dest="filterfile",
        help="A file containing a list of SRPM names to restrict the lookup",
        default="view-source-package-name-list--view-eln.txt",
    )

    ap.add_argument("outfile", help="File to hold the output JSON")

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

    with open(args.filterfile) as filterfile:
        filter_packagenames = filterfile.read().splitlines()

    session = koji.ClientSession(args.kojihub)
    latest_builds = session.listTagged(args.tag, latest=True)

    logger.debug(f"Latest builds: {latest_builds}")
    logger.info(f"Builds in tag: {len(latest_builds)}")

    filtered_builds = [
        build
        for build in latest_builds
        if build["name"] in filter_packagenames
    ]

    logger.debug(f"Filtered builds: {filtered_builds}")
    logger.info(f"Filtered builds: {len(filtered_builds)}")

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_build_source = dict()

        for build in filtered_builds:
            future = executor.submit(
                get_build_source, session, build["name"], build["nvr"]
            )
            future_to_build_source[future] = build["nvr"]

        for future in as_completed(future_to_build_source):
            result = future.result()
            logger.debug(result)
            spkg_list[result["name"]] = result

    with open(args.outfile, "w") as json_file:
        json.dump(spkg_list, json_file, indent=2, sort_keys=True)


def get_build_source(session, name, nvr):
    buildinfo = session.getBuild(nvr)
    logger.debug(f"Build source: {buildinfo['source']}")
    return {"name": name, "nvr": nvr, "githash": buildinfo["source"]}


if __name__ == "__main__":
    main()
