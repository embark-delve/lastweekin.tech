"""Pure text and URL helpers shared across the pipeline.

Everything here is deterministic and network-free so it can be unit tested
directly; the pipeline stages compose these helpers.
"""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that identify the referrer rather than the document, so two
# URLs that differ only in these point at the same article.
_TRACKING_PARAMS = re.compile(
    r"^(utm_[a-z_]+|ref|ref_src|referrer|source|fbclid|gclid|igshid|mc_cid|mc_eid|__twitter_impression)$",
    re.IGNORECASE,
)

# Terms that mark a story as AI-related. Order matters: longer, punctuated
# variants come first so that "a.i." wins over the bare "ai" alternative.
_AI_TERMS: list[str] = [
    r"a\.i\.",
    r"ai",
    r"agi",
    r"llms?",
    r"genai",
    r"artificial intelligence",
    r"machine learning",
    r"deep learning",
    r"neural networks?",
    r"large language models?",
    r"foundation models?",
    r"language models?",
    r"generative ai",
    r"chatbots?",
    r"transformers? model",
    r"diffusion models?",
    r"openai",
    r"anthropic",
    r"claude",
    r"chatgpt",
    r"gpt-?[0-9o]+",
    r"gemini",
    r"copilot",
    r"deepmind",
    r"deepseek",
    r"hugging ?face",
    r"midjourney",
    r"stable diffusion",
    # Model families. A release post is the most common shape of AI story and
    # its headline is often just the model name.
    r"qwen",
    r"glm",
    r"llama",
    r"mistral",
    r"mixtral",
    r"gemma",
    r"grok",
    r"kimi",
    r"minimax",
    r"sora",
    r"cohere",
    r"perplexity",
    # Anthropic's model families. These are only matched when a version number
    # follows: bare "Opus" is an audio codec, "Sonnet" is a Thunderbolt dock
    # brand and a "haiku" is a poem, so the number is what makes them a model.
    r"opus[- ]?[0-9]",
    r"sonnet[- ]?[0-9]",
    r"haiku[- ]?[0-9]",
    # Vocabulary that only appears around model work. "prompt" is deliberately
    # absent: it is far more often a verb in a headline ("outage prompts
    # review") than a noun about models.
    r"inference",
    r"fine-?tun\w*",
    r"hallucinat\w*",
    r"system prompt",
    r"prompt engineering",
    r"agentic",
    r"ai agents?",
    r"training data",
    r"model weights",
]

_SECURITY_TERMS: list[str] = [
    r"vulnerabilit(?:y|ies)",
    r"exploits?",
    r"exploited",
    r"zero[- ]days?",
    r"zero-?click",
    r"malware",
    r"ransomware",
    r"phishing",
    r"breach(?:es|ed)?",
    r"hacked",
    r"hackers?",
    r"hacking",
    r"cyber ?attacks?",
    r"cyber ?security",
    r"cybercrim\w*",
    r"cve-?[0-9]*",
    r"backdoors?",
    r"spyware",
    r"botnets?",
    r"ddos",
    r"trojans?",
    r"rootkits?",
    r"infostealers?",
    r"infiltrat\w*",
    r"exfiltrat\w*",
    r"patch tuesday",
    r"security (?:flaws?|updates?|researchers?|advisor(?:y|ies))",
    r"cred(?:ential)s?",
    r"authentication",
    r"encrypt\w*",
    r"password",
    r"2fa",
    r"attackers?",
    r"threat actors?",
    r"data leaks?",
    r"leaked data",
    r"privilege escalation",
    r"remote code execution",
    r"supply chain attack",
    r"malicious (?:packages?|code|apps?|extensions?)",
    r"antivirus",
    r"firewall",
    r"intrusion",
    r"bug bount\w*",
    r"sim swap",
    r"spoof\w*",
    r"scams?",
    r"fraud",
]

_POLICY_TERMS: list[str] = [
    r"regulat\w*",
    r"antitrust",
    r"anticompetitive",
    r"monopol\w*",
    r"lawsuits?",
    r"sues?",
    r"sued",
    r"courts?",
    r"judges?",
    r"ftc",
    r"fcc",
    r"doj",
    r"gdpr",
    r"congress",
    r"senate",
    r"parliament",
    r"bans?",
    r"banned",
    r"legislation",
    r"laws?",
    r"bills?",
    r"subpoena",
    r"settlements?",
    r"copyright",
    r"patents?",
    r"tariffs?",
    r"sanctions?",
    r"policy",
    r"rulings?",
    r"illegal",
    r"compliance",
    r"europ\w*",
    r"eu",
    r"white house",
    r"government",
    r"federal",
    r"censorship",
    r"surveillance",
    r"fined",
    r"probe",
    r"executive order",
    r"supreme court",
    r"attorney general",
    r"whistleblower",
    r"export controls?",
    # "privacy" alone labelled a phone review with a privacy screen as policy.
    r"privacy (?:law|policy|rules?|watchdog)",
    r"data protection",
    r"age verification",
    r"age-?checks?",
    r"right-?to-?repair",
    r"net neutrality",
    r"public domain",
    r"plead(?:s|ed)? guilty",
    r"indict\w*",
    r"charged with",
    r"sentenced",
    r"extradit\w*",
]

_OPEN_SOURCE_TERMS: list[str] = [
    r"open[- ]?source",
    r"github",
    r"gitlab",
    r"linux",
    r"kernel",
    r"debian",
    r"ubuntu",
    r"fedora",
    r"gpl",
    r"apache",
    r"mozilla",
    r"firefox",
    r"rust",
    r"python",
    r"kubernetes",
    r"postgres\w*",
    r"mysql",
    r"docker",
    r"foss",
    r"blender",
    r"libreoffice",
    r"npm",
    r"systemd",
    r"ffmpeg",
    r"curl",
    r"sqlite",
    r"node\.?js",
    r"wordpress",
    r"wikipedia",
    r"self-?hosted",
    r"maintainers?",
    r"repositor(?:y|ies)",
    r"golang",
    r"typescript",
    r"javascript",
    r"webassembly",
    r"chromium",
    r"vscode",
    r"emacs",
]

_HARDWARE_TERMS: list[str] = [
    r"chips?",
    r"processors?",
    r"cpus?",
    r"gpus?",
    r"silicon",
    r"semiconductors?",
    r"laptops?",
    r"smartphones?",
    r"iphones?",
    r"tablets?",
    r"wearables?",
    r"headphones?",
    r"earbuds?",
    r"ssds?",
    r"ram",
    r"ddr[0-9]",
    r"motherboards?",
    r"raspberry pi",
    r"risc-?v",
    r"x86",
    r"nvidia",
    r"amd",
    r"intel",
    r"tsmc",
    r"qualcomm",
    r"foundry",
    r"transistors?",
    r"batter(?:y|ies)",
    r"robots?",
    r"robotics",
    r"drones?",
    r"consoles?",
    r"cameras?",
    r"printers?",
    r"quantum comput\w*",
    r"wafers?",
    r"displays?",
    r"keyboards?",
    r"monitors?",
    r"snapdragon",
    r"apple silicon",
    r"m[0-9] (?:chip|max|pro|ultra)",
    r"hardware",
    r"gadgets?",
    r"macbook",
    r"steam deck",
    r"playstation",
    r"xbox",
    r"routers?",
    r"phones?",
    r"cams?",
    r"webcams?",
    r"headsets?",
    r"handhelds?",
    r"chargers?",
    r"docks?",
    r"e-?readers?",
    r"speakers?",
    r"smartwat\w*",
    r"thunderbolt",
    r"usb-?c",
    r"hard drives?",
    r"nvme",
    # Product lines whose bare name is an ordinary English word: "switch" is a
    # verb, a "galaxy" is astronomy and "pixel" is a unit of a screen.
    r"nintendo switch",
    r"switch 2",
    r"google pixel",
    r"pixel [0-9]",
    r"galaxy (?:s|z|a|note|tab|watch|buds|fold|flip)",
    r"vision pro",
    r"data ?cent(?:er|re)s?",
    r"servers?",
    r"nodes?",
]

_BUSINESS_TERMS: list[str] = [
    r"acquisitions?",
    r"acquires?",
    r"acquired",
    r"mergers?",
    r"ipo",
    r"funding",
    r"valuation",
    r"revenue",
    r"earnings",
    r"layoffs?",
    r"startups?",
    r"venture capital",
    r"investors?",
    r"stocks?",
    r"market cap",
    r"ceos?",
    r"cfo",
    r"quarterly",
    r"profits?",
    r"buyout",
    r"bankrupt\w*",
    r"subscriptions?",
    r"paywall",
    r"pricing",
    r"monetiz\w*",
    r"shareholders?",
    r"partnerships?",
    r"hiring",
    r"workforce",
    r"restructur\w*",
    r"job cuts?",
    r"price hikes?",
    r"spin-?offs?",
    # Money verbs only when money follows: a bare "raises" is usually about a
    # price or an eyebrow, and "deals"/"sales" matched every shopping listicle.
    r"series [abcd] round",
    r"raises \$[0-9]",
    r"raised \$[0-9]",
    r"[0-9]+ (?:billion|million) deal",
    r"takes? a stake",
]

AI_CATEGORY = "AI"
GENERAL_CATEGORY = "General Tech"

# Categories are tested in this order and the first match wins, so a story
# about an AI security hole lands in "AI" rather than wherever the regexes
# happened to fire. AI leads because it is the spine of the digest and the
# category ``digest.min_ai_stories`` counts; the residual is not in the list
# because it is what a story gets when nothing else matched.
_TAXONOMY: tuple[tuple[str, list[str]], ...] = (
    (AI_CATEGORY, _AI_TERMS),
    ("Security", _SECURITY_TERMS),
    ("Policy", _POLICY_TERMS),
    ("Open Source", _OPEN_SOURCE_TERMS),
    ("Hardware", _HARDWARE_TERMS),
    ("Business", _BUSINESS_TERMS),
)

CATEGORY_PRECEDENCE: tuple[str, ...] = tuple(name for name, _ in _TAXONOMY)

# Every category string the front end has to style, residual last.
CATEGORIES: tuple[str, ...] = (
    "AI",
    "Security",
    "Policy",
    "Hardware",
    "Open Source",
    "Business",
    GENERAL_CATEGORY,
)


def _compile(terms: list[str]) -> re.Pattern[str]:
    """Compile ``terms`` into one word-bounded alternation.

    Guard both sides with alphanumeric lookarounds rather than ``\\b``: ``\\b``
    would still match the "ai" inside "Britain", "train", "email" and "Aids".
    """
    return re.compile(
        r"(?<![a-z0-9])(?:" + "|".join(terms) + r")(?![a-z0-9])",
        re.IGNORECASE,
    )


_CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {
    name: _compile(terms) for name, terms in _TAXONOMY
}

_AI_PATTERN = _CATEGORY_PATTERNS[AI_CATEGORY]

# A sentence terminator, optionally followed by a closing quote or bracket, that
# is followed by whitespace or the end of the text. Decimal points fail the
# lookahead because a digit follows them.
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]?(?=\s|$)")  # noqa: RUF001 - curly quotes intended


def normalize_url(url: str) -> str:
    """Return a canonical form of ``url`` for identity comparisons."""
    if not url:
        return ""

    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    query = urlencode([
        (key, value) for key, value in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(key)
    ])
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def count_category_terms(text: str | None, category: str) -> int:
    """Count occurrences of ``category``'s terms in ``text``.

    Raises :class:`KeyError` for a category outside the taxonomy, so a typo in a
    caller fails loudly instead of silently scoring zero.
    """
    pattern = _CATEGORY_PATTERNS[category]
    if not text:
        return 0
    return len(pattern.findall(text))


def contains_category_terms(text: str | None, category: str) -> bool:
    """Return True when ``text`` mentions a term from ``category``."""
    return count_category_terms(text, category) > 0


def classify_text(text: str | None) -> str:
    """Return the highest-precedence category ``text`` matches.

    Falls back to the residual category, which is why the precedence tuple does
    not contain it.
    """
    for category in CATEGORY_PRECEDENCE:
        if contains_category_terms(text, category):
            return category
    return GENERAL_CATEGORY


def count_ai_terms(text: str | None) -> int:
    """Count AI-related term occurrences in ``text``."""
    return count_category_terms(text, AI_CATEGORY)


def contains_ai_terms(text: str | None) -> bool:
    """Return True when ``text`` mentions an AI-related term."""
    return count_ai_terms(text) > 0


def trim_to_sentence(text: str) -> str:
    """Drop a trailing partial sentence left behind by a truncated generation."""
    stripped = text.strip()
    matches = list(_SENTENCE_END.finditer(stripped))
    if not matches:
        return stripped

    trimmed = stripped[: matches[-1].end()].strip()
    return trimmed or stripped
