from setuptools import setup

setup(
    name='rfscan',
    packages=['rfscan'],
    include_package_data=True,
    install_requires=[
        'flask',
        'flask_socketio',
    ],
)
