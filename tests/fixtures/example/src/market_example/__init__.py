"""An independently installed contrib with a published configuration model."""

from bazaar_core import Contrib
from pydantic import BaseModel


class Settings(BaseModel):
    message: str = "Hello from the selected computer"


example = Contrib(config=Settings)
