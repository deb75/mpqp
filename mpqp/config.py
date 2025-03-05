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
__active_profile: str = ""


class ConfigError(ValueError):
    """Raised any time an error occurs at configuration level."""


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


def is_loaded(provider: str | None = None):
    return (data != None) and (
        (provider.upper() in data.keys()) if (provider != None) else True
    )


def get_active_profile() -> str:
    return __active_profile


def unset_active_profile():
    __active_profile = ""


def is_set_active_profile(provider: str | None = None):
    if is_loaded(provider) and __active_profile:
        if provider != None:
            if provider.upper() != __active_profile.split("|")[0]:
                raise ConfigError(
                    "Active profile \"%s\" is not valid for given provider \"%s\""
                    % (__active_profile, provider.upper())
                )
            else:
                return True
        else:
            return True
    else:
        return False


def set_active_profile(profile_name: str, provider: str | None = None) -> None:
    global __active_profile

    if not is_loaded(provider):
        raise ConfigError(
            "No configuration file loaded. Try \"config.load()\" at first."
        )

    if provider is not None:
        if (
            provider.upper()
            not in data.keys()  # pyright: ignore[reportOptionalMemberAccess]
        ):
            raise ConfigError("Unknown provider \"%s\"" % provider)
        else:
            if profile_name not in data[provider.upper()]["profile"]:
                raise ConfigError(
                    "Unknown profile name \"%s\" for provider \"%s\""
                    % (profile_name, provider)
                )
            else:
                __active_profile = provider.upper() + "|" + profile_name
    else:
        # If names of profiles are unique across all providers,
        # it is enough to give only the profile name.
        __active_profile = ""

        for key_provider in data.keys():  # pyright: ignore[reportOptionalMemberAccess]
            if profile_name in data[key_provider]["profile"].keys():
                __active_profile = key_provider + "|" + profile_name
                break

        if not __active_profile:
            raise ConfigError(
                "Could not find profile name \"%s\" across all providers \"%s\""
                % (
                    profile_name,
                    str(data.keys()),  # pyright: ignore[reportOptionalMemberAccess]
                )
            )
    __logger.info("Active profile set to \"%s\"" % __active_profile)


def get_active_profile_data():
    """Warning : This function does not perform any check.  You are supposed to perform
    these checks before : configuration loaded, existing profile and profile
    corresponding to desired provider

    """
    provider, profile_name = __active_profile.split("|")
    return data[provider]["profile"][profile_name]
