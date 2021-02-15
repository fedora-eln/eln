# Lists for compare.py
These lists will eventually be pulled from where they are generated.  
But for now, while those parts are getting written, we have them stored as flat files here.

## exclude.txt
These packages should never be built, synced, or even counted.

We are still deciding where to put this list.  It is currently a list in eln-periodic.py

## nosync.txt
These are the packages that should not be synced from Fedora to RHEL and/or CentOS Stream.

This list is in a yaml file here - https://gitlab.cee.redhat.com/osci/distrobaker_config/-/raw/rhel9/distrobaker.yaml

compare.py now gets this information from the above URL. The nosync.txt file is no longer used by compare.py and will go away soon.
