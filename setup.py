from setuptools import setup

VERSION = "0.11"

setup(
    name="hass-nabucasa",
    version=VERSION,
    license="GPL v3",
    author="Nabu Casa, Inc.",
    author_email="opensource@nabucasa.com",
    url="https://www.nabucasa.com/",
    download_url="https://github.com/NabuCasa/hass-nabucasa/tarball/{}".format(VERSION),
    description=("Home Assistant cloud integration by Nabu Casa, inc."),
    long_description=(""),
    classifiers=[
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Topic :: Internet :: Proxy Servers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Development Status :: 5 - Production/Stable",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    keywords=["homeassistant", "cloud"],
    zip_safe=False,
    platforms="any",
    packages=["hass_nabucasa"],
    install_requires=[
        "warrant==0.6.1",
        "snitun==0.18",
        "acme==0.32.0",
        "cryptography>=2.5",
        "attrs>=18.2.0",
        "pytz",
    ],
)
