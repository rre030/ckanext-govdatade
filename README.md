# ckanext-govdatade

GovData.de specific CKAN extension

### Dependencies

The GovData.de harvester relies on a group import feature, which is currently not implemented in the `ckanext-harvest`. Therefore a [fork][fork] with a feature branch is used as the dependency instead.

## Getting Started

If you are using Python virtual environment (virtualenv), activate it.

```
$ pip install -e git+git://github.com/fraunhoferfokus/ckanext-govdatade.git#egg=ckanext-govdatade
$ cd /path/to/virtualenv/src/ckanext-govdatade
$ pip install -r pip-requirements
$ python setup.py develop

$ cd /path/to/virtualenv/src/ckanext-harvester
$ pip install -r pip-requirements
$ python setup.py develop
```

Add the following plugins to your CKAN configuration file:

```
ckan.plugins = harvest ckan_harvester hamburg_harvester rlp_harvester berlin_harvester
```

Please make sure, that the CKAN process will have access to the logfile specified in `/path/to/virtualenv/src/ckanext-govdata/ckanext/govdatade/harvesters/config.ini`. After restarting CKAN the plugins should be ready to use.

[fork]: https://github.com/fraunhoferfokus/ckanext-harvest

## Testing

Unit tests are placed in the `ckanext/govdatade/tests` directory and can be run with the nose unit testing framework:

```
$ cd /path/to/virtualenv/src/ckanext-govdatade
$ nosetests
```
