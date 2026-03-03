from setuptools import setup, find_packages

setup(
    name="cynthia",
    version="0.0.0",
    packages=["cynthia", "bot", "utils", "context"],
    install_requires=["discord.py"],
)
