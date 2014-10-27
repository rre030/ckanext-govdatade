#!/usr/bin/python
# -*- coding: utf8 -*-

from ckanext.harvest.harvesters.ckanharvester import CKANHarvester
from ckanext.harvest.model import HarvestObject
from ckanext.govdatade.harvesters.translator import translate_groups
from ckanext.govdatade.util import iterate_local_datasets
from ckanext.govdatade.validators.link_checker import LinkChecker
from ckanext.govdatade import CONFIG

from ckan import model
from ckan.logic import get_action
from ckan.logic.schema import default_package_schema
from ckan.model import Session

import json
import logging
import urllib2
import uuid


log = logging.getLogger(__name__)


def assert_author_fields(package_dict, author_alternative,
                         author_email_alternative):
    """Ensures that the author field is set."""

    if not 'author' in package_dict or not package_dict['author']:
        package_dict['author'] = author_alternative

    if not 'author_email' in package_dict or not package_dict['author_email']:
        package_dict['author_email'] = author_email_alternative

    if not package_dict['author']:
        raise ValueError('There is no author for package %s' % package_dict['id'])


def resolve_json_incosistency(dataset):
    return dataset


class GroupCKANHarvester(CKANHarvester):
    """
    An extended CKAN harvester that also imports remote groups, for that api
    version 1 is enforced
    """

    api_version = 1
    """Enforce API version 1 for enabling group import"""

    def __init__(self):
        schema_url = 'https://raw.githubusercontent.com/fraunhoferfokus/ogd-metadata/master/OGPD_JSON_Schema.json' #CONFIG.get('URLs', 'schema')
        groups_url = 'https://raw.githubusercontent.com/fraunhoferfokus/ogd-metadata/master/kategorien/deutschland.json' #CONFIG.get('URLs', 'groups')
        self.schema = json.loads(urllib2.urlopen(schema_url).read())
        self.govdata_groups = json.loads(urllib2.urlopen(groups_url).read())
        self.link_checker = LinkChecker()

    def _set_config(self, config_str):
        """Enforce API version 1 for enabling group import"""
        if config_str:
            self.config = json.loads(config_str)
        else:
            self.config = {}
        self.api_version = 1
        self.config['api_version'] = 1
        self.config['force_all'] = True
        self.config['remote_groups'] = 'only_local'

    def import_stage(self, harvest_object):
        package_dict = json.loads(harvest_object.content)
        delete = self.link_checker.process_record(package_dict)
        # deactivated until broken links are fixed
        if delete:
            package_dict['state'] = 'deleted'
        else:
            if 'deprecated' not in package_dict['tags']:
                package_dict['state'] = 'active'

        try:
            self.amend_package(package_dict)
        except ValueError, e:
            self._save_object_error(str(e), harvest_object)
            log.error('Rostock: ' + str(e))
            return
        harvest_object.content = json.dumps(package_dict)
        super(GroupCKANHarvester, self).import_stage(harvest_object)


class GovDataHarvester(GroupCKANHarvester):
    """The base harvester for GovData.de perfoming remote synchonization."""

    def build_context(self):
        return {'model':       model,
                'session':     Session,
                'user':        u'harvest',
                'schema':      default_package_schema(),
                'validate':    False,
                'api_version': 1}

    def portal_relevant(self, portal):
        def condition_check(dataset):
            for extra in dataset['extras']:
                if extra['key'] == 'metadata_original_portal':
                    value = extra['value']
                    value = value.lstrip('"').rstrip('"')
                    return value == portal

            return False

        return condition_check

    def delete_deprecated_datasets(self, context, remote_dataset_names):
        package_update = get_action('package_update')

        local_datasets = iterate_local_datasets(context)
        filtered = filter(self.portal_relevant(self.PORTAL), local_datasets)
        local_dataset_names = map(lambda dataset: dataset['name'], filtered)

        deprecated = set(local_dataset_names) - set(remote_dataset_names)
        log.info('Found %s deprecated datasets.' % len(deprecated))

        for local_dataset in filtered:
            if local_dataset['name'] in deprecated:
                local_dataset['state'] = 'deleted'
                local_dataset['tags'].append({'name': 'deprecated'})
                package_update(context, local_dataset)

    def gather_stage(self, harvest_job):
        """Retrieve local datasets for synchronization."""

        self._set_config(harvest_job.source.config)
        content = self._get_content(harvest_job.source.url)

        base_url = harvest_job.source.url.rstrip('/')
        base_rest_url = base_url + self._get_rest_api_offset()
        url = base_rest_url + '/package'

        try:
            content = self._get_content(url)
        except Exception, e:
            error = 'Unable to get content for URL: %s: %s' % (url, str(e))
            self._save_gather_error(error, harvest_job)
            return None

        context = self.build_context()
        remote_datasets = json.loads(content)
        remote_dataset_names = map(lambda d: d['name'], remote_datasets)

        self.delete_deprecated_datasets(context, remote_dataset_names)
        super(GovDataHarvester, self).gather_stage(harvest_job)


class RostockCKANHarvester(GovDataHarvester):
    """A CKAN Harvester for Rostock solving data compatibility problems."""

    PORTAL = 'http://www.opendata-hro.de'

    def info(self):
        return {'name':        'rostock',
                'title':       'Rostock Harvester',
                'description': 'A CKAN Harvester for Rostock solving data'
                'compatibility problems.'}

    def amend_package(self, package):
        portal = 'http://www.opendata-hro.de'
        package['extras']['metadata_original_portal'] = portal
        package['name'] = package['name'] + '-hro'
        for resource in package['resources']:
                resource['format'] = resource['format'].lower()

    def import_stage(self, harvest_object):
        package_dict = json.loads(harvest_object.content)
        try:
            self.amend_package(package_dict)
        except ValueError, e:
            self._save_object_error(str(e), harvest_object)
            log.error('Rostock: ' + str(e))
            return
        harvest_object.content = json.dumps(package_dict)
        super(RostockCKANHarvester, self).import_stage(harvest_object)


class HamburgCKANHarvester(GovDataHarvester):
    """A CKAN Harvester for Hamburg solving data compatibility problems."""

    def info(self):
        return {'name':        'hamburg',
                'title':       'Hamburg Harvester',
                'description': 'A CKAN Harvester for Hamburg solving data compatibility problems.'}

    def amend_package(self, package):

        # fix usage of hyphen, the schema group names use underscores
        package['groups'] = [name.replace('-', '_') for name in package['groups']]

        # add tag for better searchability
        package['tags'].append(u'Hamburg')
	for resource in package['resources']:
		resource['format'] = resource['format'].lower()

        assert_author_fields(package, package['maintainer'],
                             package['maintainer_email'])

    def import_stage(self, harvest_object):
        package_dict = json.loads(harvest_object.content)
        try:
            self.amend_package(package_dict)
        except ValueError, e:
            self._save_object_error(str(e), harvest_object)
            log.error('Hamburg: ' + str(e))
            return
        harvest_object.content = json.dumps(package_dict)
        super(HamburgCKANHarvester, self).import_stage(harvest_object)


class BerlinCKANHarvester(GovDataHarvester):
    """A CKAN Harvester for Berlin sovling data compatibility problems."""

    def info(self):
        return {'name':        'berlin',
                'title':       'Berlin Harvester',
                'description': 'A CKAN Harvester for Berlin solving data compatibility problems.'}

    def amend_package(self, package):

        extras = package['extras']

        if package['license_id'] == '':
            package['license_id'] = 'notspecified'

        # if sector is not set, set it to 'oeffentlich' (default)
        if not extras.get('sector'):
            extras['sector'] = 'oeffentlich'

        if package['extras']['sector'] != 'oeffentlich':
            return False

        valid_types = ['datensatz', 'dokument', 'app']
        if not package.get('type') or package['type'] not in valid_types:
            package['type'] = 'datensatz'

        package['groups'] = translate_groups(package['groups'], 'berlin')
        default_portal = 'http://datenregister.berlin.de'
        if not extras.get('metadata_original_portal'):
            extras['metadata_original_portal'] = default_portal
        for resource in package['resources']:
                resource['format'] = resource['format'].lower()
        return True

    def import_stage(self, harvest_object):
        package_dict = json.loads(harvest_object.content)
        valid = self.amend_package(package_dict)

        if not valid:
            return  # drop package

        harvest_object.content = json.dumps(package_dict)
        super(BerlinCKANHarvester, self).import_stage(harvest_object)


class RLPCKANHarvester(GovDataHarvester):
    """A CKAN Harvester for Rhineland-Palatinate sovling data compatibility problems."""

    def info(self):
        return {'name':        'rlp',
                'title':       'RLP Harvester',
                'description': 'A CKAN Harvester for Rhineland-Palatinate solving data compatibility problems.'}

    def __init__(self):
	schema_url = 'https://raw.githubusercontent.com/fraunhoferfokus/ogd-metadata/master/OGPD_JSON_Schema.json' #CONFIG.get('URLs', 'schema')
        groups_url = 'https://raw.githubusercontent.com/fraunhoferfokus/ogd-metadata/master/kategorien/deutschland.json' #CONFIG.get('URLs', 'groups')

        self.schema = json.loads(urllib2.urlopen(schema_url).read())
        self.govdata_groups = json.loads(urllib2.urlopen(groups_url).read())
        self.link_checker = LinkChecker()

    def amend_package(self, package_dict):
        # manually set package type
        if all([resource['format'].lower() == 'pdf' for resource in package_dict['resources']]):
            package_dict['type'] = 'dokument'
        else:
            package_dict['type'] = 'datensatz'

        for resource in package['resources']:
                resource['format'] = resource['format'].lower()

        assert_author_fields(package_dict, package_dict['point_of_contact'],
                             package_dict['point_of_contact_address']['email'])

        package_dict['extras']['metadata_original_portal'] = 'http://daten.rlp.de'
        package_dict['extras']['sector'] = 'oeffentlich'

        # the extra fields are present as CKAN core fields in the remote
        # instance: copy all content from these fields into the extras field
        for extra_field in self.schema['properties']['extras']['properties'].keys():
            if extra_field in package_dict:
                package_dict['extras'][extra_field] = package_dict[extra_field]
                del package_dict[extra_field]

        # convert license cc-by-nc to cc-nc
        if package_dict['extras']['terms_of_use']['license_id'] == 'cc-by-nc':
            package_dict['extras']['terms_of_use']['license_id'] = 'cc-nc'

        package_dict['license_id'] = package_dict['extras']['terms_of_use']['license_id']

        # GDI related patch
        if 'gdi-rp' in package_dict['groups']:
            package_dict['type'] = 'datensatz'

        # map these two group names to schema group names
        if 'justiz' in package_dict['groups']:
            package_dict['groups'].append('gesetze_justiz')
            package_dict['groups'].remove('justiz')

        if 'transport' in package_dict['groups']:
            package_dict['groups'].append('transport_verkehr')
            package_dict['groups'].remove('transport')

        # filter illegal group names
        package_dict['groups'] = [group for group in package_dict['groups'] if group in self.govdata_groups]

    def import_stage(self, harvest_object):
        package_dict = json.loads(harvest_object.content)

        dataset = package_dict['extras']['content_type'].lower() == 'datensatz'
        if not dataset and not 'gdi-rp' in package_dict['groups']:
            return  # skip all non-datasets for the time being

        try:
            self.amend_package(package_dict)
        except ValueError, e:
            self._save_object_error(str(e), harvest_object)
            log.error('RLP: ' + str(e))
            return

        harvest_object.content = json.dumps(package_dict)
        super(RLPCKANHarvester, self).import_stage(harvest_object)


class JSONDumpBaseCKANHarvester(GovDataHarvester):

    def info(self):
        return {'name':        'base',
                'title':       'Base Harvester',
                'description': 'A Base CKAN Harvester for CKANs which return a JSON dump file.'}

    def gather_stage(self, harvest_job):
        self._set_config(harvest_job.source.config)
        # Request all remote packages
        try:
            content = self._get_content(harvest_job.source.url)
        except Exception, e:
            self._save_gather_error('Unable to get content for URL: %s: %s' % (harvest_job.source.url, str(e)), harvest_job)
            return None

        object_ids = []

        packages = json.loads(content)
        for package in packages:
            obj = HarvestObject(guid=package['name'], job=harvest_job)
            obj.content = json.dumps(package)
            obj.save()
            object_ids.append(obj.id)

        context = self.build_context()
        remote_dataset_names = map(lambda d: d['name'], packages)
        self.delete_deprecated_datasets(context, remote_dataset_names)

        if object_ids:
            return object_ids
        else:
            self._save_gather_error('No packages received for URL: %s' % harvest_job.source.url,
                                    harvest_job)
            return None

    def fetch_stage(self, harvest_object):
        self._set_config(harvest_object.job.source.config)

        if harvest_object.content:
            return True
        else:
            return False


class BremenCKANHarvester(JSONDumpBaseCKANHarvester):
    '''
    A CKAN Harvester for Bremen. The Harvester retrieves a JSON dump,
    which will be loaded to CKAN.
    '''
    def info(self):
        return {'name':        'bremen',
                'title':       'Bremen CKAN Harvester',
                'description': 'A CKAN Harvester for Bremen.'}

    def amend_package(self, package):
        '''
        This function fixes some differences in the datasets retrieved from Bremen and our schema such as:
        - fix groups
        - set metadata_original_portal
        - fix terms_of_use
        - copy veroeffentlichende_stelle to maintainer
        - set spatial text
        '''

        #set metadata original portal
        package['extras']['metadata_original_portal'] = 'http://daten.bremen.de/sixcms/detail.php?template=export_daten_json_d'

        # set correct groups
        if not package['groups']:
            package['groups'] = []
        package['groups'] = translate_groups(package['groups'], 'bremen')

        #copy veroeffentlichende_stelle to maintainer
        if 'contacts' in package['extras']:
            quelle = filter(lambda x: x['role'] == 'veroeffentlichende_stelle', package['extras']['contacts'])[0]
            package['maintainer'] = quelle['name']
            package['maintainer_email'] = quelle['email']

        #fix typos in terms of use
        if 'terms_of_use' in package['extras']:
            self.fix_terms_of_use(package['extras']['terms_of_use'])
            #copy license id
            package['license_id'] = package['extras']['terms_of_use']['license_id']
        else:
            package['license_id'] = u'notspecified'

        if not "spatial-text" in package["extras"]:
            package["extras"]["spatial-text"] = 'Bremen 04 0 11 000'

        #generate id based on OID namespace and package name, this makes sure,
        #that packages with the same name get the same id
        package['id'] = str(uuid.uuid5(uuid.NAMESPACE_OID, str(package['name'])))

        for resource in package['resources']:
                resource['format'] = resource['format'].lower()

    def import_stage(self, harvest_object):
        package = json.loads(harvest_object.content)

        self.amend_package(package)

        harvest_object.content = json.dumps(package)
        super(BremenCKANHarvester, self).import_stage(harvest_object)

    def fix_terms_of_use(self, terms_of_use):
        terms_of_use['license_id'] = terms_of_use['licence_id']
        del(terms_of_use['licence_id'])
        terms_of_use['license_url'] = terms_of_use['licence_url']
        del(terms_of_use['licence_url'])


class BayernCKANHarvester(JSONDumpBaseCKANHarvester):
    '''
    A CKAN Harvester for Bavaria. The Harvester retrieves a JSON dump,
    which will be loaded to CKAN.
    '''

    def info(self):
        return {'name':        'bayern',
                'title':       'Bavarian CKAN Harvester',
                'description': 'A CKAN Harvester for Bavaria.'}

    def amend_package(self, package):
        if len(package['name']) > 100:
            package['name'] = package['name'][:100]
        if not package['groups']:
            package['groups'] = []

        #copy autor to author
        quelle = {}
        if 'contacts' in package['extras']:
            quelle = filter(lambda x: x['role'] == 'autor', package['extras']['contacts'])[0]

        if not package['author'] and quelle:
            package['author'] = quelle['name']
        if not package['author_email']:
            if 'email' in quelle:
                package['author_email'] = quelle['email']

        if not "spatial-text" in package["extras"].keys():
            package["extras"]["spatial-text"] = 'Bayern 09'
        for r in package['resources']:
            r['format'] = r['format'].upper()

        #generate id based on OID namespace and package name, this makes sure,
        #that packages with the same name get the same id
        package['id'] = str(uuid.uuid5(uuid.NAMESPACE_OID, str(package['name'])))
        for resource in package['resources']:
                resource['format'] = resource['format'].lower()

    def import_stage(self, harvest_object):
        package = json.loads(harvest_object.content)

        self.amend_package(package)

        harvest_object.content = json.dumps(package)
        super(BayernCKANHarvester, self).import_stage(harvest_object)


class MoersCKANHarvester(JSONDumpBaseCKANHarvester):
    """A CKAN Harvester for Moers solving data compatibility problems."""

    PORTAL = 'http://www.offenedaten.moers.de/'

    def info(self):
        return {'name':        'moers',
                'title':       'Moers Harvester',
                'description': 'A CKAN Harvester for Moers solving data compatibility problems.'}

    def amend_dataset_name(self, dataset):
        dataset['name'] = dataset['name'].replace(u'ä', 'ae')
        dataset['name'] = dataset['name'].replace(u'ü', 'ue')
        dataset['name'] = dataset['name'].replace(u'ö', 'oe')

        dataset['name'] = dataset['name'].replace('(', '')
        dataset['name'] = dataset['name'].replace(')', '')
        dataset['name'] = dataset['name'].replace('.', '')
        dataset['name'] = dataset['name'].replace('/', '')
        dataset['name'] = dataset['name'].replace('http://www.moers.de', '')

    def amend_package(self, package):

        publishers = filter(lambda x: x['role'] == 'veroeffentlichende_stelle', package['extras']['contacts'])
        maintainers = filter(lambda x: x['role'] == 'ansprechpartner', package['extras']['contacts'])

        if not publishers:
            raise ValueError('There is no author email for package %s' % package_dict['id'])

        self.amend_dataset_name(package)
        package['id'] = str(uuid.uuid5(uuid.NAMESPACE_OID, str(package['name'])))
        package['name'] = package['name'].lower()

        if 'moers' not in package['title'].lower():
            package['title'] = package['title'] + ' Moers'

        package['author'] = 'Stadt Moers'
        package['author_email'] = publishers[0]['email']

        if maintainers:
            package['maintainer'] = maintainers[0]['name']
            package['maintainer_email'] = maintainers[0]['email']

        package['license_id'] = package['extras']['terms_of_use']['license_id']
        package['extras']['metadata_original_portal'] = 'http://www.offenedaten.moers.de/'

        if not "spatial-text" in package["extras"].keys():
            package["extras"]["spatial-text"] = '05 1 70 024 Moers'

        if isinstance(package['tags'], basestring):
            if not package['tags']:  # if tags was set to "" or null
                package['tags'] = []
            else:
                package['tags'] = [package['tags']]
        package['tags'].append('moers')

        for resource in package['resources']:
            resource['format'] = resource['format'].replace('text/comma-separated-values', 'XLS')
            resource['format'] = resource['format'].replace('application/json', 'JSON')
            resource['format'] = resource['format'].replace('application/xml', 'XML')

        for resource in package['resources']:
                resource['format'] = resource['format'].lower()

    def import_stage(self, harvest_object):
        package_dict = json.loads(harvest_object.content)
        try:
            self.amend_package(package_dict)
        except ValueError, e:
            self._save_object_error(str(e), harvest_object)
            log.error('Moers: ' + str(e))
            return
        harvest_object.content = json.dumps(package_dict)
        super(MoersCKANHarvester, self).import_stage(harvest_object)


class GovAppsHarvester(JSONDumpBaseCKANHarvester):
    '''
    A CKAN Harvester for GovApps. The Harvester retrieves a JSON dump,
    which will be loaded to CKAN.
    '''

    def info(self):
        return {'name':        'govapps',
                'title':       'GovApps Harvester',
                'description': 'A CKAN Harvester for GovApps.'}

    def amend_package(self, package):
        if not package['groups']:
            package['groups'] = []
        #fix groups
        if not package['groups']:
            package['groups'] = []
        package['groups'] = [x for x in translate_groups(package['groups'], 'govapps') if len(x) > 0]

        #generate id based on OID namespace and package name, this makes sure,
        #that packages with the same name get the same id
        package['id'] = str(uuid.uuid5(uuid.NAMESPACE_OID, str(package['name'])))
        
	for resource in package['resources']:
                resource['format'] = resource['format'].lower()

    def import_stage(self, harvest_object):
        package = json.loads(harvest_object.content)

        self.amend_package(package)

        harvest_object.content = json.dumps(package)
        super(GovAppsHarvester, self).import_stage(harvest_object)


class JSONZipBaseHarvester(JSONDumpBaseCKANHarvester):
    
    def info(self):
        return {'name':        'zipbase',
                'title':       'Base Zip Harvester',
                'description': 'A Harvester for Portals, which return JSON files in a zip file.'}

    def gather_stage(self, harvest_job):
        self._set_config(harvest_job.source.config)
        # Request all remote packages
        try:
            content = self._get_content(harvest_job.source.url)
        except Exception, e:
            self._save_gather_error('Unable to get content for URL: %s: %s' % (harvest_job.source.url, str(e)), harvest_job)
            return None

        object_ids = []
	packages = []
        import zipfile
	import StringIO
	file_content = StringIO.StringIO(content)
        archive = zipfile.ZipFile(file_content, "r")
        for name in archive.namelist():
	    print name
	    if name.endswith(".json"):
		package = json.loads(archive.read(name))
		packages.append(package)
		obj = HarvestObject(guid=package['name'], job=harvest_job)
           	obj.content = json.dumps(package)
            	obj.save()
            	object_ids.append(obj.id)
	'''
        context = self.build_context()
        remote_dataset_names = map(lambda d: d['name'], packages)
        self.delete_deprecated_datasets(context, remote_dataset_names)
        
	'''

	if object_ids:
            return object_ids
        else:
            self._save_gather_error('No packages received for URL: %s' % harvest_job.source.url,
                                    harvest_job)
            return None


class BKGHarvester(JSONZipBaseHarvester):
    PORTAL = 'http://ims.geoportal.de/'

    def info(self):
        return {'name':        'bkg',
                'title':       'BKG CKAN Harvester',
                'description': 'A CKAN Harvester for BKG.'}

    def amend_package(self, package):
	#generate id based on OID namespace and package name, this makes sure,
        #that packages with the same name get the same id
        package['id'] = str(uuid.uuid5(uuid.NAMESPACE_OID, str(package['name'])))
        package['extras']['metadata_original_portal'] = 'http://ims.geoportal.de/'
        for resource in package['resources']:
                resource['format'] = resource['format'].lower()

    def import_stage(self, harvest_object):
        package = json.loads(harvest_object.content)

        self.amend_package(package)

        harvest_object.content = json.dumps(package)
        super(JSONZipBaseHarvester, self).import_stage(harvest_object)


class DestatisZipHarvester(JSONZipBaseHarvester):
    PORTAL = 'http://destatis.de/'
    def info(self):
        return {'name':        'destatis',
                'title':       'Destatis CKAN Harvester',
                'description': 'A CKAN Harvester for destatis.'}

    def amend_package(self, package):
        #generate id based on OID namespace and package name, this makes sure,
        #that packages with the same name get the same id
	package['name'] = package['name'] + "-test"
        package['id'] = str(uuid.uuid5(uuid.NAMESPACE_OID, str(package['name'])))
        package['extras']['metadata_original_portal'] = 'http://destatis.de/'
        for resource in package['resources']:
                resource['format'] = resource['format'].lower()

    def import_stage(self, harvest_object):
        package = json.loads(harvest_object.content)

        self.amend_package(package)

        harvest_object.content = json.dumps(package)
        super(JSONZipBaseHarvester, self).import_stage(harvest_object)


class DatahubCKANHarvester(GroupCKANHarvester):
    """A CKAN Harvester for Datahub IO importing a small set of packages."""

    portal = 'http://datahub.io/'

    valid_packages = ['hbz_unioncatalog', 'lobid-resources',
                      'deutsche-nationalbibliografie-dnb',
                      'dnb-gemeinsame-normdatei']

    def info(self):
        return {'name':        'datahub',
                'title':       'Datahub IO Harvester',
                'description': 'A CKAN Harvester for Datahub IO importing a '
                               'small set of packages.'}

    def fetch_stage(self, harvest_object):
        log.debug('In CKANHarvester fetch_stage')
        self._set_config(harvest_object.job.source.config)

        if harvest_object.guid not in DatahubCKANHarvester.valid_packages:
            return None

        # Get source URL
        url = harvest_object.source.url.rstrip('/')
        url = url + self._get_rest_api_offset() + '/package/'
        url = url + harvest_object.guid

        # Get contents
        try:
            content = self._get_content(url)
        except Exception, e:
            self._save_object_error('Unable to get content for package:'
                                    '%s: %r' % (url, e), harvest_object)
            return None

        # Save the fetched contents in the HarvestObject
        harvest_object.content = content
        harvest_object.save()
        return True

    def package_valid(self, package_name):
        return package_name in DatahubCKANHarvester.valid_packages

    def amend_package(self, package_dict):
        portal = DatahubCKANHarvester.portal

        package_dict['type'] = 'datensatz'
        # Currently, only the description is displayed. Some datasets only have
        # a descriptive name, but no description. Hence, it is copied if unset.
        for resource in package_dict['resources']:
            description = resource['description'].lower()
            name = resource['name']

            name_valid = name and not name.isspace()
            description_invalid = not description or description.isspace()
            type_only = 'rdf/xml' in description

            if description_invalid or (type_only and name_valid):
                resource['description'] = resource['name']

        for resource in package['resources']:
                resource['format'] = resource['format'].lower()

        package_dict['extras']['metadata_original_portal'] = portal
        package_dict['groups'].append('bildung_wissenschaft')
        package_dict['groups'] = [group for group in package_dict['groups']
                                  if group in self.govdata_groups]

class KoelnCKANHarvester(GroupCKANHarvester):
    '''
    A CKAN Harvester for Koeln. The Harvester retrieves a JSON dump,
    which will be loaded to CKAN.
    '''
    def info(self):
        return {'name':        'koeln',
                'title':       'Koeln CKAN Harvester',
                'description': 'A CKAN Harvester for Koeln.'}



    def gather_stage(self, harvest_job):
        """Retrieve datasets"""
        
        log.debug('In KoelnCKANHarvester gather_stage (%s)' % harvest_job.source.url)
        package_ids = []
        self._set_config(None)

        base_url = harvest_job.source.url.rstrip('/')
        package_list_url = base_url + '/3/action/package_list'
        content = self._get_content(package_list_url)
        
        content_json = json.loads(content)
        package_ids = content_json['result']

        try:
            object_ids = []
            if len(package_ids):
                for package_id in package_ids:                                      
                    obj = HarvestObject(guid = package_id, job = harvest_job)
                    obj.save()
                    object_ids.append(obj.id)
                return object_ids

            else:
               self._save_gather_error('No packages received for URL: %s' % url,
                       harvest_job)
               return None
        except Exception, e:
            self._save_gather_error('%r'%e.message,harvest_job)



    def fetch_stage(self,harvest_object):
        log.debug('In KoelnCKANHarvester fetch_stage')
        self._set_config(None)
       
        # Get contents
        package_get_url = ''
        try:    
            base_url = harvest_object.source.url.rstrip('/')
      
            package_get_url = base_url + '/3/ogdp/action/package_show?id=' + harvest_object.guid
            content = self._get_content(package_get_url.encode("utf-8"))
            package = json.loads(content)
            harvest_object.content = json.dumps(package['result'][0])
            harvest_object.save()

        except Exception,e:
            self._save_object_error('Unable to get content for package: %s: %r' % \
                                        (package_get_url, e),harvest_object)
            return None

        return True

    def import_stage(self, harvest_object):
        package_dict = json.loads(harvest_object.content)
        try:
            self.amend_package(package_dict)
        except ValueError, e:
            self._save_object_error(str(e), harvest_object)
            log.error('Koeln: ' + str(e))
            return
      
        harvest_object.content = json.dumps(package_dict)
        super(KoelnCKANHarvester, self).import_stage(harvest_object)

    def amend_package(self, package):
        # map these two group names to schema group names
        out = []
        if 'Geo' in package['groups']:
            package['groups'].append('geo')
            package['groups'].remove('Geo')

        if 'Bildung und Wissenschaft' in package['groups']:
            package['groups'].append(u'bildung_wissenschaft')
            package['groups'].remove('Bildung und Wissenschaft')

        if 'Gesetze und Justiz' in package['groups']:
            package['groups'].append(u'gesetze_justiz')
            package['groups'].remove('Gesetze und Justiz')

        if 'Gesundheit' in package['groups']:
            package['groups'].append(u'gesundheit')
            package['groups'].remove('Gesundheit')
                  
        if 'Infrastruktur' in package['groups']:
            package['groups'].append(u'infrastruktur_bauen_wohnen')
            package['groups'].remove('Infrastruktur')
            package['groups'].remove('Bauen und Wohnen')
            
        if 'Kultur' in package['groups']:
            package['groups'].append(u'kultur_freizeit_sport_tourismus')
            package['groups'].remove('Kultur')
            package['groups'].remove('Freizeit')
            package['groups'].remove('Sport und Tourismus')
            
        if 'Politik und Wahlen' in package['groups']:
            package['groups'].append(u'politik-wahlen')
            package['groups'].append('Politik und Wahlen')
            
        if 'Soziales' in package['groups']:
            package['groups'].append(u'soziales')   
            package['groups'].remove('Soziales')   

        if 'Transport und Verkehr' in package['groups']:
            package['groups'].append(u'transport_verkehr')
            package['groups'].remove('Transport und Verkehr')     
         
        if 'Umwelt und Klima' in package['groups']:
            package['groups'].append(u'umwelt_klima')   
            package['groups'].remove('Umwelt und Klima')      
             
        if 'Verbraucherschutz' in package['groups']:
            package['groups'].append(u'verbraucher') 
            package['groups'].remove('Verbraucherschutz')  
            
        if 'Verwaltung' in package['groups']:
            package['groups'].append(u'verwaltung')
            package['groups'].remove('Verwaltung')   
            package['groups'].remove('Haushalt und Steuern') 
                    
     
        if 'Wirtschaft und Arbeit' in package['groups']:
            package['groups'].append(u'wirtschaft_arbeit')
            package['groups'].remove('Wirtschaft und Arbeit')           
        
        for cat in package['groups']:
            if 'Bev' in cat:
                package['groups'].append(u'bevoelkerung')   

	from ckan.lib.munge import munge_title_to_name
        name = package['name']
        try:
            name = munge_title_to_name(name).replace('_', '-')
            while '--' in name:
                name = name.replace('--', '-')
        except Exception,e:   
                log.debug('Encoding Error ' + str(e))
            
        package['name'] = name

 class RegionalStatistikZipHarvester(JSONZipBaseHarvester):

	def info(self):
		return {'name': 'regionalStatistik',
			'title': 'RegionalStatistik CKAN Harvester',
			'description': 'A CKAN Harvester for Regional Statistik.'}
			
	def amend_package(self, package):
	#generate id based on OID namespace and package name, this makes sure,
	#that packages with the same name get the same id
		package['id'] = str(uuid.uuid5(uuid.NAMESPACE_OID, str(package['name'])))
		package['name'] = package['name']+'rre'
		package['extras']['metadata_original_portal'] = 'https://www.regionalstatistik.de/'
		for resource in package['resources']:
			resource['format'] = resource['format'].lower()
			
	def import_stage(self, harvest_object):
		package = json.loads(harvest_object.content)
		self.amend_package(package)
		harvest_object.content = json.dumps(package)
		super(JSONZipBaseHarvester, self).import_stage(harvest_object)       

