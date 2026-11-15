from twoworlds.content.schema import Identifier, Version

from .identity import StrictModel


class CreateSave(StrictModel):
    pair_id: Identifier
    script_id: Identifier
    script_version: Version
