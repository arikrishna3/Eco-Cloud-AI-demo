from google.cloud import secretmanager

client = secretmanager.SecretManagerServiceClient()

def access_secret(secret_id, version_id=1):
    project_id = "273345197968"
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")