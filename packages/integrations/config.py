"""Secret-isolated account configuration; does NOT imply authorized live API support."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, SecretStr, Field, HttpUrl

class ProviderConfig(BaseModel):
    model_config=ConfigDict(extra='forbid')
    provider:Literal['coupang','temu','aliexpress']
    seller_account_id:str=Field(default='',max_length=120)
    client_id:str=Field(default='',max_length=200)
    client_secret:SecretStr=SecretStr('')
    access_token:SecretStr=SecretStr('')
    refresh_token:SecretStr=SecretStr('')
    oauth_redirect_uri:HttpUrl|None=None
    documented_scopes:list[str]=Field(default_factory=list)
    account_permissions_verified:bool=False
    documentation_reference:str=Field(default='',max_length=500)

    def readiness(self):
        if not self.client_id or not self.client_secret.get_secret_value():return 'BLOCKED_BY_CREDENTIALS'
        if not self.account_permissions_verified or not self.documentation_reference:return 'BLOCKED_BY_PROVIDER_ACCESS'
        # Credentials cannot unlock code that has not been implemented and certified.
        return 'BLOCKED_BY_CONNECTOR_IMPLEMENTATION'
