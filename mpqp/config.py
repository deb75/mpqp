import json as __json
import platform as __platform
import os as __os
import sys as __sys
import logging as __logging
import gnupg as __gnupg


__logger = __logging.getLogger(__name__)
__logger.setLevel(__logging.DEBUG)

handler = __logging.StreamHandler(__sys.stderr)
handler.setLevel(__logging.DEBUG)
formatter = __logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Comment out this line below if you do no more want any logging messages
__logger.addHandler(handler)

# __logger.removeHandler(handler)

DEFAULT_CONFIG_FILE = [
    (
        __os.path.join(__os.environ["USERPROFILE"], ".config", "mpqp.json.gpg")
        if "Windows" in __platform.system()
        else __os.path.join(
            (
                __os.environ["XDG_CONFIG_HOME"]
                if "XDG_CONFIG_HOME" in __os.environ.keys()
                else __os.environ["HOME"]
            ),
            "mpqp.gpg",
        )
    ),
    (
        __os.path.join(__os.environ["USERPROFILE"], ".mpqp.json.gpg")
        if "Windows" in __platform.system()
        else __os.path.join(__os.environ["HOME"], ".mpqp.json.gpg")
    ),
    (
        __os.path.join(__os.environ["USERPROFILE"], ".config", "mpqp.json")
        if "Windows" in __platform.system()
        else __os.path.join(
            (
                __os.environ["XDG_CONFIG_HOME"]
                if "XDG_CONFIG_HOME" in __os.environ.keys()
                else __os.environ["HOME"]
            ),
            "mpqp.json",
        )
    ),
    (
        __os.path.join(__os.environ["USERPROFILE"], ".mpqp.json")
        if "Windows" in __platform.system()
        else __os.path.join(__os.environ["HOME"], ".mpqp.json")
    ),
]

__logger.info("Default config file list set to " + str(DEFAULT_CONFIG_FILE))


data = None
ibm = None
aws = None
qlm = None


def load(configFile: str | None = None):
    if configFile is None:
        for f in DEFAULT_CONFIG_FILE:
            __logger.info("Trying file \"%s\"" % f)
            if __os.path.isfile(f):
                configFile = f
                break

    if configFile is not None:
        configStr: str | None = None

        if configFile.endswith("gpg"):
            gpg = __gnupg.GPG(use_agent=True)
            gpg.encoding = "utf-8"
            decryptData = gpg.decrypt_file(open(configFile, mode="rb"), passphrase=None)

            if decryptData.ok:  # pyright: ignore[reportAttributeAccessIssue]
                configStr = str(decryptData)
            else:
                __logger.error(
                    "Decryption failed with message \"%s\""
                    % decryptData.status  # pyright: ignore[reportAttributeAccessIssue]
                )
        else:
            with open(configFile, mode="rb") as fi:
                configStr = fi.read()

        if configStr is not None:
            global data, ibm, aws, qlm
            data = __json.loads(configStr)
            ibm = data['IBM'] if 'IBM' in data.keys() else None
            aws = data['AWS'] if 'AWS' in data.keys() else None
            qlm = data['QLM'] if 'QLM' in data.keys() else None


use_profile = None
