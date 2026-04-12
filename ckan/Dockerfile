FROM ckan/ckan-base:2.11

# Install any extensions needed by your CKAN instance
# See Dockerfile.dev for more details and examples



# Copy custom initialization scripts
COPY --chown=ckan-sys:ckan-sys docker-entrypoint.d/* /docker-entrypoint.d/
COPY ./schemas /srv/app/schemas
COPY ./extensions/ckanext-geodcatap /srv/app/extensions/ckanext-geodcatap
COPY --chown=ckan-sys:ckan-sys setup/map-catalogue.png /srv/app/src/ckan/ckan/public/base/images/map-catalogue.png
COPY --chown=ckan-sys:ckan-sys setup/promoted.html.override /srv/app/src/ckan/ckan/templates/home/snippets/promoted.html

USER root
# Install dependencies for spatial extensions
RUN apt-get update && apt-get install -y \
       python3-dev \
       libxml2-dev \
       libxslt1-dev \
       libgeos-dev \
       libgdal-dev \
       gdal-bin \
       python3-gdal
RUN pip install --no-cache-dir pyproj shapely geoalchemy2 OWSLib
RUN pip install --no-cache-dir geojson
RUN pip install --no-cache-dir pika redis requests #for harvest extension
RUN pip install --no-cache-dir git+https://github.com/ckan/ckanext-harvest.git
RUN pip install --no-cache-dir git+https://github.com/ckan/ckanext-scheming.git#egg=ckanext-scheming
RUN pip install --no-cache-dir git+https://github.com/ckan/ckanext-spatial.git
RUN pip install --no-cache-dir git+https://github.com/ckan/ckanext-geoview.git
RUN pip install --no-cache-dir ckanext-dcat
RUN pip install --no-cache-dir /srv/app/extensions/ckanext-geodcatap


# Apply any patches needed to CKAN core or any of the built extensions (not the
# runtime mounted ones)
COPY --chown=ckan-sys:ckan-sys patches ${APP_DIR}/patches

USER ckan

RUN for d in $APP_DIR/patches/*; do \
        if [ -d $d ]; then \
            for f in `ls $d/*.patch | sort -g`; do \
                cd $SRC_DIR/`basename "$d"` && echo "$0: Applying patch $f to $SRC_DIR/`basename $d`"; patch -p1 < "$f" ; \
            done ; \
        fi ; \
    done
