from setuptools import setup, find_packages

from version import VERSION

DESCRIPTION = "A trading framework for cryptocurrencies"

REQUIRED_PACKAGES = [
    'requests',
    'easygui',
    'PySimpleGUI',
    'numpy',
    'reportlab',
    'anytree'
]

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name='erpnext client',
    version=VERSION,
    author="Till Mossakowski",
    author_email="till@communtu.de",
    packages=find_packages(),
    description=DESCRIPTION,
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=REQUIRED_PACKAGES,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GPL License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.1',
    include_package_data=True,
)
