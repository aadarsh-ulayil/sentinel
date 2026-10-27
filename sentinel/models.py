"""HTTP and rule contracts. Reject extra fields and unknown rule types."""
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

Tool = Literal['list_files','read_file','write_file','delete_file','run_command','fetch_url','send_message','spend_money']
RuleType = Literal['path_allowlist','count_limit','cumulative_limit','per_call_threshold','regex_block','recipient_allowlist','command_rules','domain_allowlist','download_block']

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Action(Strict):
    run_id: str = Field(min_length=1, max_length=100)
    tool: Tool
    args: dict[str, Any]
    agent_note: str = Field(default='', max_length=2000)

class Rule(Strict):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    type: RuleType
    limit: int | None = Field(default=None, ge=0, le=10000000)
    values: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def required_limit(self):
        if self.type in {'count_limit','cumulative_limit','per_call_threshold','download_block'} and self.limit is None:
            raise ValueError('This rule requires an integer limit')
        return self

class Verdict(Strict):
    verdict: Literal['allow','pause','block']
    rule_id: str
    reason: str
