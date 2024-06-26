from setuptools import find_packages, setup

setup(
    name="t5gweb",
    version="1.240110",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "flask==2.2.2",
        "gunicorn==20.1.0",
        "jira==3.4.1",
        "requests==2.28.1",
        "slack_sdk==3.19.4",
        "redis==4.3.4",
        "python_bugzilla==3.2.0",
        "celery==5.3.6",
        "flower==1.2.0",
        "python3-saml==1.15.0",
        "flask-login==0.6.2",
        "prometheus-flask-exporter==0.22.4",
        "Werkzeug==2.3.7",
        "xmlsec==1.3.13",
    ],
)
