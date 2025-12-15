#!/bin/bash

# Add scheming configuration if not present
if ! grep -q "ckan.scheming.dataset_schemas" /srv/app/ckan.ini; then
    #ckan config-tool /srv/app/ckan.ini "scheming.dataset_schemas = ckanext.scheming:ckan_dataset.json"
    #ckan config-tool /srv/app/ckan.ini "scheming.presets = ckanext.scheming:presets.json"
    ckan config-tool /srv/app/ckan.ini "scheming.dataset_schemas = file:///srv/app/schemas/geodataset.yaml"
    ckan config-tool /srv/app/ckan.ini "scheming.presets = ckanext.scheming:presets.json"
    echo "[Scheming] Config added via ckan config-tool"

    #echo "" >> /srv/app/ckan.ini
    #echo "## Scheming settings" >> /srv/app/ckan.ini
    #echo "scheming.dataset_schemas = file:///srv/app/schemas/geodataset.yaml" >> /srv/app/ckan.ini
    #echo "scheming.dataset_schemas = ckanext.scheming:ckan_dataset.json" >> /srv/app/ckan.ini    
    #echo "scheming.presets = ckanext.scheming:presets.json" >> /srv/app/ckan.ini
    #echo "[Scheming] Configuration added to ckan.ini"
else
    echo "[Scheming] Configuration already present in ckan.ini"
fi
