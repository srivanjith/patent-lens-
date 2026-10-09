import re
from typing import List, Dict, Tuple, Any
from sklearn.feature_extraction.text import TfidfVectorizer

GENERIC_DOMAIN_NOISE = {
    "vehicle", "vehicles", "charging", "system", "systems", "method", "methods",
    "device", "devices", "apparatus", "comprising", "includes", "including",
    "provides", "provided", "configured", "based", "monitoring", "control",
    "controlling", "data", "algorithm", "algorithms", "application", "applications",
    "process", "processing", "unit", "units", "module", "modules", "operation",
    "operating", "user", "time", "real", "high", "low", "new", "improved",
    "mechanism", "component", "feature", "information", "technology",
    "medical", "image", "images", "ai", "deep", "learning", "detection", "analysis",
    "technique", "model", "result", "smart", "type", "mode"
}

TECHNICAL_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with",
    "by", "about", "against", "between", "into", "through", "during", "before",
    "after", "above", "below", "from", "up", "down", "out", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "any", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "s", "t", "can", "will", "just", "don", "should", "now", "using", "used",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "having",
    "do", "does", "did", "doing", "would", "could", "ought"
}

# Technical synonyms & acronym mapping dictionary for patent retrieval
TECHNICAL_SYNONYMS_MAP = {
    "state of health": ["soh", "battery health status", "degradation state", "battery capacity retention"],
    "soh": ["state of health", "battery health", "health status", "capacity degradation"],
    "foreign object detection": ["fod", "foreign object sensing", "parasitic metal detection", "abnormal body detection"],
    "fod": ["foreign object detection", "foreign object sensing", "parasitic load detection"],
    "wireless power transfer": ["wpt", "wireless charging", "inductive power transfer", "resonant energy transfer", "near-field charging"],
    "wpt": ["wireless power transfer", "wireless charging", "inductive charging"],
    "semiconductor": ["transistor", "solid-state device", "semiconductive element", "bipolar junction"],
    "soil moisture": ["soil humidity", "volumetric water content", "ground moisture level"],
    "neural network": ["deep learning model", "machine learning architecture", "artificial neural network", "predictive model"],
    "impedance matching": ["impedance tuning", "resonant matching circuit", "reflection coefficient minimization"],
    "geneva drive": ["geneva mechanism", "maltese cross mechanism", "intermittent gear drive"],
    "cam and follower": ["cam mechanism", "cam-actuated follower", "rotary cam follower assembly"],
    "spiking neural network": ["snn", "neuromorphic network", "event-driven neural model"],
    "vertical-cavity surface-emitting laser": ["vcsel", "surface-emitting semiconductor laser", "vcsel array"],
    "lidar point cloud": ["laser scanner point cloud", "3d lidar measurement", "spatial point cloud data"],
    "waste segregation": ["waste sorting", "garbage classification", "refuse separation", "trash sorting", "recyclable material sorting"],
    "waste sorting": ["waste segregation", "garbage classification", "trash sorting", "material separation"],
    "material classification": ["waste material identification", "waste type recognition", "trash category classification"]
}

# Domain-specific highly distinctive technical terms that signal specialized technical IP
DISTINCTIVE_TECHNICAL_TERMS = {
    # Waste Segregation & Automated Recycling
    "waste segregation", "waste sorting", "automated waste sorting", "material classification",
    "recyclable sorting", "waste item identification", "pneumatic sorting actuator",
    "optical waste sensor", "trash classification", "destination container routing",
    "waste material separation", "garbage classification", "refuse separation",

    # Mechanical Engineering & Indexing
    "continuous rotary input", "intermittent rotary output", "multiple gear arrangement",
    "gears connected by links", "orbital gear movement", "indexed/step-by-step movement",
    "step-by-step movement", "dwell period", "cam and follower", "reverse-motion prevention",
    "indexing mechanism", "geneva drive", "geneva wheel", "ratchet and pawl", "globoidal cam",
    "roller follower", "intermittent motion mechanism", "epicyclic gear", "holding pawl",

    # Electrical & Wireless Power
    "wireless power transfer", "foreign object detection", "impedance measurement",
    "impedance matching", "resonant frequency", "charging coil", "transmitter coil",
    "receiver coil", "electromagnetic field", "inductive charging", "resonant charging",
    "abnormal condition detection", "dynamic threshold", "temperature compensation",
    "automatic power reduction", "power interruption", "spiking neural network",
    "vertical-cavity surface-emitting laser", "gan power transistor",

    # AI, Robotics & Software
    "sensor fusion", "multispectral", "hyperspectral", "piezoelectric", "thermoelectric",
    "galvo-steered", "solenoid", "impedance", "inductance", "capacitance", "reactance",
    "telemetry", "convolutional neural network", "spatial transformer network", "lidar point cloud",
    "4-bit quantization", "unsupervised generative adversarial network", "proximal policy optimization",
    "contrastive learning", "impedance control", "stereo fisheye camera", "9-axis imu",
    "solid-state electrolyte", "bifacial tandem photovoltaic cell", "melt pool thermal monitoring",
    "zero-copy memory management", "zero-knowledge proof", "cas12 trans-cleavage"
}

def get_synonyms_for_term(term: str) -> List[str]:
    """Retrieve technical synonyms and acronym expansions for a given term."""
    term_lower = term.lower().strip()
    synonyms = []
    for key, syn_list in TECHNICAL_SYNONYMS_MAP.items():
        if key in term_lower or term_lower in key:
            for syn in syn_list:
                if syn.lower() != term_lower and syn not in synonyms:
                    synonyms.append(syn)
    return synonyms

def clean_technical_feature_phrase(phrase: str) -> str:
    """Clean feature phrase by stripping leading/trailing generic noise words and incomplete n-gram fragments."""
    if not phrase:
        return ""
    words = phrase.strip().split()
    NOISE_HEAD_TAIL = {
        "based", "using", "collected", "smart", "system", "device", "method", "unit",
        "module", "for", "with", "from", "via", "type", "mode", "process", "apparatus",
        "technology", "mechanism", "data", "information"
    }
    
    # Strip leading noise words
    while words and words[0].lower() in NOISE_HEAD_TAIL:
        words.pop(0)
    # Strip trailing noise words
    while words and words[-1].lower() in NOISE_HEAD_TAIL:
        words.pop()
        
    cleaned = " ".join(words).strip()
    if len(cleaned.split()) == 1 and cleaned.lower() in NOISE_HEAD_TAIL:
        return ""
    return cleaned.title()

def extract_structured_invention_features(text: str) -> Dict[str, Any]:
    """
    Decompose invention disclosure into complete technical feature objects formatted as
    Component + Function + Relationship + Purpose quadruplets, separating essential
    features from optional features.
    """
    if not text or len(text.strip()) < 5:
        return {
            "essential_features": [],
            "optional_features": [],
            "structured_quadruplets": [],
            "synonyms_map": {}
        }

    lower_text = text.lower()
    atomic_features = extract_atomic_technical_features(text, top_n=10)

    structured_quadruplets = []
    essential_features = []
    optional_features = []
    synonyms_map = {}

    # Extract sentences containing structural actions / relationships
    sentences = [s.strip() for s in re.split(r'[\.\;\n]', text) if len(s.strip()) > 15]

    for feat in atomic_features:
        feat_cleaned = clean_technical_feature_phrase(feat)
        if not feat_cleaned or feat_cleaned.lower() in GENERIC_DOMAIN_NOISE:
            continue

        feat = feat_cleaned
        feat_lower = feat.lower()

        syns = get_synonyms_for_term(feat)
        if syns:
            synonyms_map[feat] = syns

        # Determine essential vs optional status based on distinctiveness and multi-word structure
        is_distinctive = feat_lower in DISTINCTIVE_TECHNICAL_TERMS or len(feat.split()) >= 3
        is_essential = is_distinctive or len(feat.split()) == 2

        weight = 3.0 if is_distinctive else (2.0 if is_essential else 1.0)

        # Locate sentence containing this feature to build quadruplet (Component + Function + Relationship + Purpose)
        matching_sentence = next((s for s in sentences if feat_lower in s.lower()), None)

        if matching_sentence:
            comp_match = feat
            func_match = f"operates using {feat_lower}"
            rel_match = "coupled to system processing module"
            purp_match = "to optimize operational accuracy"

            if "to " in matching_sentence.lower():
                parts = re.split(r'\bto\b', matching_sentence, flags=re.IGNORECASE)
                if len(parts) >= 2:
                    purp_match = f"to {parts[1].strip()[:60]}"
                    func_match = parts[0].strip()[:80]

            quad = {
                "feature": feat,
                "component": comp_match,
                "function": func_match,
                "relationship": rel_match,
                "purpose": purp_match,
                "quadruplet_text": f"{comp_match} -> {func_match} [{rel_match}] -> {purp_match}",
                "is_essential": is_essential,
                "weight": weight,
                "synonyms": syns
            }
        else:
            quad = {
                "feature": feat,
                "component": feat,
                "function": f"provides {feat.lower()} functionality",
                "relationship": "integrated within system architecture",
                "purpose": "improves technical performance",
                "quadruplet_text": f"{feat} -> provides {feat.lower()} functionality",
                "is_essential": is_essential,
                "weight": weight,
                "synonyms": syns
            }

        structured_quadruplets.append(quad)
        if is_essential:
            essential_features.append(feat)
        else:
            optional_features.append(feat)

    if not essential_features and atomic_features:
        essential_features = atomic_features[:4]
        optional_features = atomic_features[4:]

    return {
        "essential_features": essential_features,
        "optional_features": optional_features,
        "structured_quadruplets": structured_quadruplets,
        "synonyms_map": synonyms_map
    }

def extract_atomic_technical_features(text: str, top_n: int = 9) -> List[str]:
    """
    Extract atomic technical feature items (6-9 items) from target invention text.
    Combines domain-specific matching with TF-IDF phrase decomposition.
    """
    if not text or len(text.strip()) < 5:
        return []

    lower_text = text.lower()
    features = []

    # 1. Direct matched distinctive phrases from domain vocabulary
    for d_term in DISTINCTIVE_TECHNICAL_TERMS:
        if d_term in lower_text:
            title_case = d_term.title()
            if not any(title_case.lower() in f.lower() or f.lower() in title_case.lower() for f in features):
                features.append(title_case)

    # 2. Key structural patterns (e.g. "x arrangement", "x mechanism", "x control")
    pattern_matches = re.findall(
        r'\b(?:continuous|intermittent|rotary|linear|orbital|gear|link|cam|follower|indexing|dwell|sensor|coil|circuit|signal|valve|laser|module|node|driver)\s+[a-z\-]+(?:\s+[a-z\-]+)?\b',
        lower_text
    )
    for p in pattern_matches:
        if len(p.split()) >= 2 and p.lower() not in GENERIC_DOMAIN_NOISE:
            p_title = p.title()
            if not any(p.lower() in f.lower() or f.lower() in p.lower() for f in features):
                features.append(p_title)

    # 3. TF-IDF Extracted phrases & distinct terms
    extracted_concepts = extract_technical_concepts(text, top_n=8)
    for c in extracted_concepts:
        if not any(c.lower() in f.lower() or f.lower() in c.lower() for f in features):
            features.append(c)

    # Clean & format nicely
    clean_features = []
    for f in features:
        if f.lower() in GENERIC_DOMAIN_NOISE:
            continue
        clean_features.append(f)
        if len(clean_features) >= top_n:
            break

    return clean_features if clean_features else [text.split()[0].title()]

def extract_technical_concepts(text: str, top_n: int = 8) -> List[str]:
    """
    Extract AI-detected distinctive technical concepts prioritizing multi-word n-grams
    (e.g., 'Wireless Power Transfer', 'Foreign Object Detection', 'Impedance Measurement').
    """
    if not text or len(text.strip()) < 10:
        return []
        
    cleaned = re.sub(r'[^a-zA-Z0-9\s\-]', ' ', text.lower())
    stop_set = TECHNICAL_STOP_WORDS.union(GENERIC_DOMAIN_NOISE)
    
    words = [w for w in cleaned.split() if w not in TECHNICAL_STOP_WORDS and len(w) > 2]
    if not words:
        return []
        
    documents = [cleaned]
    
    try:
        # Extract 2-gram and 3-gram phrases first to capture distinctive technical terms
        phrase_vec = TfidfVectorizer(
            stop_words=list(TECHNICAL_STOP_WORDS),
            ngram_range=(2, 3),
            max_features=40,
            min_df=1
        )
        p_matrix = phrase_vec.fit_transform(documents)
        p_names = phrase_vec.get_feature_names_out()
        p_scores = getattr(p_matrix, "toarray")()[0]
        
        phrases = [
            (p_names[i].title(), p_scores[i] * 3.0)
            for i in p_scores.argsort()[::-1]
            if len(p_names[i].split()) >= 2
        ]
        
        # Extract single word terms, filtering out generic noise
        single_vec = TfidfVectorizer(
            stop_words=list(stop_set),
            ngram_range=(1, 1),
            max_features=30,
            min_df=1
        )
        s_matrix = single_vec.fit_transform(documents)
        s_names = single_vec.get_feature_names_out()
        s_scores = getattr(s_matrix, "toarray")()[0]
        
        singles = [
            (s_names[i].title(), s_scores[i])
            for i in s_scores.argsort()[::-1]
            if s_names[i] not in GENERIC_DOMAIN_NOISE and len(s_names[i]) > 3
        ]
        
        # Combine phrases (weighted higher) and distinct single terms
        combined = sorted(phrases + singles, key=lambda x: x[1], reverse=True)
        
        unique_concepts = []
        for concept, score in combined:
            concept_str = concept.strip()
            if not any(concept_str.lower() in u.lower() or u.lower() in concept_str.lower() for u in unique_concepts):
                unique_concepts.append(concept_str)
            if len(unique_concepts) >= top_n:
                break
                
        return unique_concepts
        
    except Exception:
        # Fallback keyword extraction
        words_no_noise = [w for w in words if w not in GENERIC_DOMAIN_NOISE]
        target_words = words_no_noise if words_no_noise else words
        freq = {}
        for w in target_words:
            freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.keys(), key=lambda k: freq[k], reverse=True)
        return [w.title() for w in sorted_words[:top_n]]

def get_weighted_technical_concepts(user_keywords: List[str], user_concepts: List[str], text_input: str) -> Dict[str, float]:
    """
    Construct a dictionary of technical concepts with associated importance weights.
    Multi-word technical phrases & distinctive terms receive 3.0x - 5.0x higher weight
    than generic unigrams.
    """
    weighted_terms = {}
    
    # 1. Add explicitly passed user keywords
    for kw in (user_keywords or []):
        if not kw or not kw.strip():
            continue
        term = kw.strip().lower()
        if term in GENERIC_DOMAIN_NOISE:
            weighted_terms[term] = 0.1
        elif len(term.split()) >= 2 or term in DISTINCTIVE_TECHNICAL_TERMS:
            weighted_terms[term] = 4.0
        else:
            weighted_terms[term] = 1.5
            
    # 2. Add extracted technical concepts & atomic features
    atomic = extract_atomic_technical_features(text_input, top_n=9)
    for f in atomic:
        term = f.strip().lower()
        if term in GENERIC_DOMAIN_NOISE:
            weighted_terms[term] = 0.1
        else:
            weighted_terms[term] = 5.0

    extracted = extract_technical_concepts(text_input, top_n=10)
    for c in extracted:
        term = c.strip().lower()
        if term in GENERIC_DOMAIN_NOISE:
            weighted_terms[term] = min(weighted_terms.get(term, 0.1), 0.1)
        elif len(term.split()) >= 2 or any(d in term for d in DISTINCTIVE_TECHNICAL_TERMS):
            weighted_terms[term] = max(weighted_terms.get(term, 0.0), 4.5)
        else:
            weighted_terms[term] = max(weighted_terms.get(term, 0.0), 2.0)
            
    # 3. Explicit check for known distinctive concepts in target text_input
    lower_text = text_input.lower()
    for d_term in DISTINCTIVE_TECHNICAL_TERMS:
        if d_term in lower_text:
            weighted_terms[d_term] = 5.0

    return weighted_terms



