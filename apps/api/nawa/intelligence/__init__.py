import os

# LiteLLM downloads its model price map at import time unless this is set.
# NAWA.AI must not make outbound calls it was not asked to make.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
