from google.cloud import storage
from google.oauth2 import service_account
import os
import json

class StorageService:
    def __init__(self):
        self.bucket_name = os.getenv("GCS_BUCKET_NAME")
        if self.bucket_name:
            try:
                # Option 1: GOOGLE_CREDENTIALS_JSON env var (recommended for deployment)
                # Store the entire service account JSON as a single env variable string
                credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
                if credentials_json:
                    credentials_info = json.loads(credentials_json)
                    credentials = service_account.Credentials.from_service_account_info(
                        credentials_info,
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                    self.client = storage.Client(credentials=credentials, project=credentials_info.get("project_id"))
                    print(f"GCS initialized via GOOGLE_CREDENTIALS_JSON (project: {credentials_info.get('project_id')})")
                else:
                    # Option 2: GOOGLE_APPLICATION_CREDENTIALS file path (local dev fallback)
                    self.client = storage.Client()
                    print("GCS initialized via Application Default Credentials")

                self.bucket = self.client.bucket(self.bucket_name)
            except Exception as e:
                print(f"GCS Initialization Error: {e}")
                self.client = None
                self.bucket = None
        else:
            self.client = None
            self.bucket = None

    def upload_from_filename(self, source_file_name: str, destination_blob_name: str) -> str:
        if not self.bucket:
            return f"local://{source_file_name}"  # Fallback for local testing without GCS

        blob = self.bucket.blob(destination_blob_name)
        # Add timeout to handle large files and unstable networks
        blob.upload_from_filename(source_file_name, timeout=300)
        gcs_uri = f"gs://{self.bucket_name}/{destination_blob_name}"
        print(f"  GCS upload: {source_file_name} → {gcs_uri}")
        return gcs_uri

    def download_to_filename(self, blob_name: str, destination_file_name: str):
        if not self.bucket:
            return
        blob = self.bucket.blob(blob_name)
        blob.download_to_filename(destination_file_name, timeout=300)

    def download_to_local(self, gcs_uri: str) -> str:
        """Downloads a gs:// URI to a temporary local file and returns its path."""
        if not gcs_uri or not gcs_uri.startswith("gs://"):
            return gcs_uri # Already local or invalid
            
        if not self.bucket:
            # Fallback for local testing: remove gs:// prefix and hope it exists locally
            return gcs_uri.replace(f"gs://{self.bucket_name or 'bucket'}/", "")

        import uuid
        blob_name = gcs_uri.replace(f"gs://{self.bucket_name}/", "")
        # Extract extension if any
        ext = os.path.splitext(blob_name)[1] or ".tmp"
        local_filename = f"outputs/download_{uuid.uuid4()}{ext}"
        os.makedirs("outputs", exist_ok=True)
        
        self.download_to_filename(blob_name, local_filename)
        return local_filename

    def generate_signed_url(self, blob_name: str, expiration_minutes: int = 60, download: bool = False) -> str:
        """Generate a temporary signed URL for browser-accessible playback or download."""
        if not self.bucket:
            return None
        from datetime import timedelta
        blob = self.bucket.blob(blob_name)
        
        generation_args = {
            "version": "v4",
            "expiration": timedelta(minutes=expiration_minutes),
            "method": "GET",
            "credentials": self.client._credentials
        }
        
        if download:
            # Force browser download instead of inline playback
            filename = blob_name.split("/")[-1]
            generation_args["response_disposition"] = f'attachment; filename="{filename}"'
            
        url = blob.generate_signed_url(**generation_args)
        return url

storage_service = StorageService()
