from setuptools import find_packages, setup


setup(
    name="ckanext-geodcatap",
    version="0.1.0",
    description="Custom GeoDCAT-AP profile glue for this CKAN stack",
    packages=find_packages(),
    namespace_packages=["ckanext"],
    include_package_data=True,
    zip_safe=False,
    entry_points="""
        [ckan.rdf.profiles]
        geodcat_ap=ckanext.geodcatap.profiles:GeoDCATAPProfile
    """,
)
