"""OpenAI-compatible answer client with accurate LangSmith provider metadata."""

from langchain_openai import ChatOpenAI


class OpenRouterChatOpenAI(ChatOpenAI):
    def get_num_tokens_from_messages(self, messages, tools=None, **kwargs):
        # LangChain rejects provider-prefixed names after downloading a tokenizer.
        # Fail before that network I/O so Agent uses its existing byte estimate.
        if "/" in self.model_name and self.tiktoken_model_name is None:
            raise NotImplementedError("Token counting requires an unprefixed model name")
        return super().get_num_tokens_from_messages(messages, tools=tools, **kwargs)

    def _get_ls_params(self, stop=None, **kwargs):
        params = super()._get_ls_params(stop=stop, **kwargs)
        # ChatOpenAI otherwise overrides caller metadata with provider=openai.
        params["ls_provider"] = "openrouter"
        return params
