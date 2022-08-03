"""
Command to run a pangeo-forge recipe
"""
from apache_beam import Pipeline
from datetime import datetime
from .base import BaseCommand, common_aliases, common_flags
from pathlib import Path
import tempfile
from .. import Feedstock
from ..stream_capture import redirect_stderr, redirect_stdout
from traitlets import Bool, Type
from ..bakery.base import Bakery
from ..bakery.local import LocalDirectBakery
from pangeo_forge_recipes.storage import StorageConfig

from ..storage import TargetStorage, InputCacheStorage, MetadataCacheStorage


class Bake(BaseCommand):
    """
    Command to bake a pangeo forge recipe in a given bakery
    """
    aliases = common_aliases
    flags = common_flags | {
        'prune': (
            {'Bake': {'prune': True}},
            'Prune the recipe to run only for 2 time steps'
        )
    }

    prune = Bool(
        False,
        config=True,
        help="""
        Prune the recipe to only run for 2 time steps.

        Makes it much easier to test recipes!
        """
    )

    bakery_class = Type(
        default_value=LocalDirectBakery,
        klass=Bakery,
        config=True,
        help="""
        The Bakery to bake this recipe in.

        The Bakery (and its configuration) determine which Apache Beam
        Runner is used, and how options for it are specified.

        Defaults to LocalDirectBakery, which bakes the recipe using Apache
        Beam's "DirectRunner". It doesn't use Docker or the cloud, and runs
        everything locally. Useful only for testing!
        """,
    )

    def start(self):
        """
        Start the baking process
        """
        # Create our storage configurations. Traitlets will do its magic, populate these
        # with appropriate config from config file / commandline / defaults.
        target_storage = TargetStorage(parent=self)
        input_cache_storage = InputCacheStorage(parent=self)
        metadata_cache_storage = MetadataCacheStorage(parent=self)

        self.log.info(f'Target Storage is {target_storage}\n', extra={'status': 'setup'})
        self.log.info(f'Input Cache Storage is {input_cache_storage}\n', extra={'status': 'setup'})
        self.log.info(f'Metadata Cache Storage is {metadata_cache_storage}\n', extra={'status': 'setup'})

        # Create a temporary directory where we fetch the feedstock repo and perform all operations
        # FIXME: Support running this on an already existing repository, so users can run it
        # as they develop their feedstock
        with tempfile.TemporaryDirectory() as d:
            self.fetch(d)
            feedstock = Feedstock(Path(d))

            self.log.info("Parsing recipes...", extra={'status': 'running'})
            with redirect_stderr(self.log, {'status': 'running'}), redirect_stdout(self.log, {'status': 'running'}):
                recipes = feedstock.parse_recipes()

            if self.prune:
                # Prune all recipes if we're asked to
                recipes = {k: r.copy_pruned() for k, r in recipes.items()}

            bakery: Bakery = self.bakery_class(
                parent=self
            )

            for name, recipe in recipes.items():
                # Unique name for running this particular recipe.
                # FIXME: Should include the name of repo / ref as well somehow
                job_name=f'{name}-{recipe.sha256().hex()}-{int(datetime.now().timestamp())}'

                recipe.storage_config = StorageConfig(
                    target_storage.get_forge_target(job_name=job_name),
                    input_cache_storage.get_forge_target(job_name=job_name),
                    metadata_cache_storage.get_forge_target(job_name=job_name)
                )

                pipeline_options = bakery.get_pipeline_options(
                    job_name=job_name,
                    # FIXME: Bring this in from meta.yaml?
                    container_image='pangeo/forge:8a862dc'
                )

                # Set argv explicitly to empty so Apache Beam doesn't try to parse the commandline
                # for pipeline options - we have traitlets doing that for us.
                pipeline = Pipeline(options=pipeline_options, argv=[])
                # Chain our recipe to the pipeline. This mutates the `pipeline` object!
                pipeline | recipe.to_beam()

                # Some bakeries are blocking - if Beam is configured to use them, calling
                # pipeline.run() blocks. Some are not. We handle that here, and provide
                # appropriate feedback to the user too.
                if bakery.blocking:
                    self.log.info(f"Running job for recipe {name}\n",
                        extra={
                            'recipe': 'name',
                            'status': 'running'
                        }
                    )
                    pipeline.run()
                else:
                    result = pipeline.run()
                    job_id = result.job_id()
                    self.log.info(
                        f"Submitted job {job_id} for recipe {name}",
                        extra={
                            'job_id': job_id,
                            'recipe': name,
                            'status': 'submitted'
                        }
                    )




