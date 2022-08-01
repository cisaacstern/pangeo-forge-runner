"""
Runner for baking pangeo-forge recipes in GCP DataFlow
"""
from apache_beam.pipeline import PipelineOptions
from traitlets.config import LoggingConfigurable
from traitlets import Unicode, Bool, default
import subprocess


class DataflowRunner(LoggingConfigurable):
    project_id = Unicode(
        None,
        allow_none=True,
        config=True,
        help="""
        GCP Project to submit the Dataflow job into
        """
    )

    @default("project_id")
    def _default_project_id(self):
        """
        Set default project_id from `gcloud` if it is set
        """
        try:
            return subprocess.check_output(
                ["gcloud", "config", "get-value", "project"],
                encoding='utf-8'
            ).strip()
        except subprocess.CalledProcessError:
            return None

    region = Unicode(
        "us-central1",
        config=True,
        help="""
        GCP Region to submit the Dataflow jobs into
        """
    )

    machine_type = Unicode(
        "n1-highmem-2",
        config=True,
        help="""
        GCP Machine type to use for the Dataflow jobs
        """
    )

    use_public_ips = Bool(
        False,
        config=True,
        help="""
        Use public IPs for the Dataflow workers.

        Set to false for projects that have policies against VM
        instances having their own public IPs
        """
    )

    temp_bucket = Unicode(
        None,
        allow_none=True,
        config=True,
        help="""
        Name of temporary staging GCS bucket to use.

        *Must* be set.

        TODO: Find out what this is used for?
        """
    )

    def get_pipeline_options(self, job_name: str, container_image: str) -> PipelineOptions:
        """
        Return PipelineOptions for use with this runner
        """
        if self.temp_bucket is None:
            raise ValueError('DataflowRunner.temp_bucket must be set')
        return PipelineOptions(
            runner="DataflowRunner",
            project=self.project_id,
            job_name=job_name,
            # TODO: Update temp bucket name once we move out of 'test' phase.
            temp_location=self.temp_bucket,
            use_public_ips=self.use_public_ips,
            region=self.region,
            # https://cloud.google.com/dataflow/docs/guides/using-custom-containers#usage
            experiments=["use_runner_v2"],
            sdk_container_image=container_image,
            # https://cloud.google.com/dataflow/docs/resources/faq#how_do_i_handle_nameerrors
            save_main_session=True,
            # this might solve serialization issues; cf. https://beam.apache.org/blog/beam-2.36.0/
            pickle_library="cloudpickle",
            machine_type=self.machine_type
        )

