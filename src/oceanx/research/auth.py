"""Local server authorization. Never expose data/tools on an unauthenticated port."""
import hmac
import os

from langgraph_sdk import Auth

auth = Auth()

@auth.authenticate
async def authenticate(authorization: str | None):
    expected = "Bearer " + os.environ["OCEAN_SERVER_TOKEN"]
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise Auth.exceptions.HTTPException(status_code=401, detail="Unauthorized")
    return {"identity": "ocean-local", "permissions": ["*"]}
