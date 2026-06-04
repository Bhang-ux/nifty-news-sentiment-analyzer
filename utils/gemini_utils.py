# utils/gemini_utils.py
import google.generativeai as genai
import json
import logging

logger = logging.getLogger(__name__)

# YOUR PROVIDED NIFTY_SECTORS_QUERY_CONFIG (incorporating stock details)
NIFTY_SECTORS_QUERY_CONFIG = {
    "Nifty IT": {
        "stocks": {
            "TCS": ["Tata Consultancy Services", "TCS India", "TCS IT services", "TCS digital transformation"],
            "Infosys": ["Infosys India", "Infosys IT", "Infosys digital", "Infosys consulting"],
            "HCL Technologies": ["HCL Tech", "HCL India", "HCL IT services", "HCL cloud"],
            "Wipro": ["Wipro India", "Wipro IT", "Wipro digital", "Wipro AI"],
            "Tech Mahindra": ["Tech Mahindra India", "TechM", "Tech Mahindra IT", "Tech Mahindra 5G"],
            "LTIMindtree": ["LTIMindtree India", "LTI Mindtree", "LTIMindtree IT", "LTIMindtree digital"],
            "Mphasis": ["Mphasis India", "Mphasis IT", "Mphasis cloud", "Mphasis BFSI"],
            "Persistent Systems": ["Persistent Systems India", "Persistent IT", "Persistent software", "Persistent digital"],
            "Coforge": ["Coforge India", "Coforge IT", "Coforge digital", "Coforge BFSI"],
            "Zensar Technologies": ["Zensar India", "Zensar IT", "Zensar digital", "Zensar cloud"],
            "Oracle Financial Services": ["OFSS India", "Oracle Financial", "OFSS banking", "Oracle FS"],
            "Happiest Minds": ["Happiest Minds India", "Happiest Minds IT", "Happiest Minds digital", "Happiest Minds AI"],
            "Cyient": ["Cyient India", "Cyient IT", "Cyient engineering", "Cyient digital"],
            "Sonata Software": ["Sonata Software India", "Sonata IT", "Sonata digital", "Sonata cloud"],
            "Intellect Design Arena": ["Intellect Design India", "Intellect banking", "Intellect digital", "Intellect AI"]
        },
        "newsapi_keywords": [ # These are for the overall sector
            "Information Technology India", "Infosys", "TCS", "Wipro", "HCL Technologies",
            "Tech Mahindra", "LTIMindtree", "Mphasis", "Coforge", "Zensar Technologies", # Added some top stocks for sector query
            "software services", "cloud computing", "AI India", "cybersecurity", "data analytics",
            "NASSCOM", "IT exports", "Bengaluru tech", "Hyderabad IT", "Pune IT",
            "digital transformation", "IT startups", "Indian IT stocks", "IT hiring"
        ]
    },
    "Nifty Bank": {
        "stocks": {
            "HDFC Bank": ["HDFC Bank India", "HDFC banking", "HDFC digital banking", "HDFC loans"],
            "ICICI Bank": ["ICICI Bank India", "ICICI banking", "ICICI digital", "ICICI fintech"],
            "SBI": ["State Bank of India", "SBI banking", "SBI digital", "SBI loans"],
            "Axis Bank": ["Axis Bank India", "Axis banking", "Axis digital", "Axis fintech"],
            "Kotak Mahindra Bank": ["Kotak Bank", "Kotak Mahindra", "Kotak digital banking", "Kotak wealth"],
            "IndusInd Bank": ["IndusInd Bank India", "IndusInd banking", "IndusInd digital", "IndusInd loans"],
            "Bank of Baroda": ["Bank of Baroda India", "BOB banking", "BOB digital", "BOB PSU"],
            "PNB": ["Punjab National Bank", "PNB India", "PNB banking", "PNB digital"],
            "Canara Bank": ["Canara Bank India", "Canara banking", "Canara digital", "Canara PSU"],
            "Yes Bank": ["Yes Bank India", "Yes banking", "Yes digital", "Yes recovery"],
            "IDFC First Bank": ["IDFC First Bank", "IDFC banking", "IDFC digital", "IDFC fintech"],
            "Federal Bank": ["Federal Bank India", "Federal banking", "Federal digital", "Federal loans"],
            "Bandhan Bank": ["Bandhan Bank India", "Bandhan microfinance", "Bandhan digital", "Bandhan banking"],
            "Union Bank of India": ["Union Bank India", "Union banking", "Union digital", "Union PSU"],
            "Indian Bank": ["Indian Bank India", "Indian banking", "Indian digital", "Indian PSU"]
        },
        "newsapi_keywords": [
            "Banking India", "HDFC Bank", "ICICI Bank", "SBI", "Axis Bank", "Kotak Mahindra Bank",
            "IndusInd Bank", "Bank of Baroda", "PNB", # Added top stocks
            "RBI", "NPA India",
            "digital banking", "UPI India", "banking reforms", "fintech India", "bank loans",
            "interest rates", "monetary policy", "bank mergers", "banking stocks",
            "financial inclusion", "bank earnings"
        ]
    },
    # ... (Include ALL OTHER SECTORS with their "stocks" and "newsapi_keywords" as you provided) ...
    # Make sure all sectors from your provided list are here. For brevity, I'm omitting the full copy-paste.
    # Ensure this structure is consistent for all sectors.
     "Nifty Auto": {
        "stocks": {
            "Maruti Suzuki": ["Maruti Suzuki India", "Maruti cars", "Maruti EV", "Maruti sales"],
            "Tata Motors": ["Tata Motors India", "Tata cars", "Tata EV", "Jaguar Land Rover"],
            "Mahindra & Mahindra": ["M&M India", "Mahindra cars", "Mahindra EV", "Mahindra tractors"],
            "Bajaj Auto": ["Bajaj Auto India", "Bajaj bikes", "Bajaj EV", "Bajaj two-wheelers"],
            "Hero MotoCorp": ["Hero MotoCorp India", "Hero bikes", "Hero EV", "Hero two-wheelers"],
            "Eicher Motors": ["Eicher Motors India", "Royal Enfield", "Eicher trucks", "Eicher EV"],
            "TVS Motor": ["TVS Motor India", "TVS bikes", "TVS EV", "TVS scooters"],
            "Ashok Leyland": ["Ashok Leyland India", "Ashok trucks", "Ashok EV", "Ashok buses"],
            "Bharat Forge": ["Bharat Forge India", "Bharat auto components", "Bharat forging", "Bharat EV"],
            "Bosch": ["Bosch India", "Bosch auto components", "Bosch EV", "Bosch technology"],
            "MRF": ["MRF India", "MRF tyres", "MRF auto", "MRF manufacturing"],
            "Apollo Tyres": ["Apollo Tyres India", "Apollo auto", "Apollo manufacturing", "Apollo EV"],
            "Exide Industries": ["Exide India", "Exide batteries", "Exide EV", "Exide auto"],
            "Balkrishna Industries": ["Balkrishna Tyres", "BKT India", "BKT auto", "BKT EV"],
            "Ceat": ["Ceat India", "Ceat tyres", "Ceat auto", "Ceat EV"]
        },
        "newsapi_keywords": [
            "Automobile India", "Maruti Suzuki", "Tata Motors", "Mahindra & Mahindra", "Bajaj Auto",
            "Hero MotoCorp", "TVS Motor", "Eicher Motors", "Ashok Leyland", "Bosch India",
            "electric vehicles", "auto sales", "auto components", "FAME scheme", "BS6 norms",
            "auto exports", "auto manufacturing", "EV subsidies", "car sales", "two-wheeler India",
            "auto technology", "auto demand"
        ]
    },
    "Nifty Pharma": {
        "stocks": {
            "Sun Pharma": ["Sun Pharma India", "Sun pharmaceuticals", "Sun drugs", "Sun R&D"],
            "Dr Reddy's Labs": ["Dr Reddy's India", "Dr Reddy's pharma", "Dr Reddy's generics", "Dr Reddy's R&D"],
            "Cipla": ["Cipla India", "Cipla pharmaceuticals", "Cipla generics", "Cipla respiratory"],
            "Divi's Laboratories": ["Divi's Labs India", "Divi's pharma", "Divi's API", "Divi's R&D"],
            "Aurobindo Pharma": ["Aurobindo India", "Aurobindo pharmaceuticals", "Aurobindo generics", "Aurobindo exports"],
            "Lupin": ["Lupin India", "Lupin pharma", "Lupin generics", "Lupin R&D"],
            "Torrent Pharma": ["Torrent Pharma India", "Torrent pharmaceuticals", "Torrent generics", "Torrent exports"],
            "Alkem Laboratories": ["Alkem Labs India", "Alkem pharma", "Alkem generics", "Alkem R&D"],
            "Zydus Lifesciences": ["Zydus India", "Zydus pharma", "Zydus generics", "Zydus biosimilars"],
            "Mankind Pharma": ["Mankind Pharma India", "Mankind pharmaceuticals", "Mankind generics", "Mankind OTC"],
            "Biocon": ["Biocon India", "Biocon biotech", "Biocon biosimilars", "Biocon R&D"],
            "Glenmark Pharmaceuticals": ["Glenmark India", "Glenmark pharma", "Glenmark generics", "Glenmark R&D"],
            "Laurus Labs": ["Laurus Labs India", "Laurus pharma", "Laurus API", "Laurus R&D"],
            "Ipca Laboratories": ["Ipca Labs India", "Ipca pharma", "Ipca generics", "Ipca exports"],
            "Abbott India": ["Abbott India", "Abbott pharma", "Abbott generics", "Abbott healthcare"]
        },
        "newsapi_keywords": [
            "Pharmaceuticals India", "Sun Pharma", "Dr Reddy's Labs", "Cipla", "Aurobindo Pharma",
            "Lupin", "Divi's Laboratories", "Alkem Laboratories", "Torrent Pharma", "Zydus Lifesciences",
            "pharma exports", "generic drugs", "DCGI", "USFDA India", "pharma R&D", "drug approvals",
            "pharma stocks", "biotechnology India", "vaccine production", "pharma market",
            "pharma innovation", "pharma pricing"
        ]
    },
    "Nifty FMCG": {
        "stocks": {
            "Hindustan Unilever": ["HUL India", "Hindustan Unilever", "HUL FMCG", "HUL consumer goods"],
            "ITC": ["ITC India", "ITC FMCG", "ITC cigarettes", "ITC foods"],
            "Nestle India": ["Nestle India", "Nestle FMCG", "Nestle foods", "Nestle beverages"],
            "Britannia Industries": ["Britannia India", "Britannia biscuits", "Britannia FMCG", "Britannia foods"],
            "Dabur India": ["Dabur India", "Dabur FMCG", "Dabur ayurveda", "Dabur consumer"],
            "Godrej Consumer Products": ["Godrej Consumer India", "Godrej FMCG", "Godrej soaps", "Godrej haircare"],
            "Colgate-Palmolive India": ["Colgate India", "Colgate FMCG", "Colgate toothpaste", "Colgate oral care"],
            "Marico": ["Marico India", "Marico FMCG", "Marico oils", "Marico haircare"],
            "United Spirits": ["United Spirits India", "USL India", "United Spirits liquor", "USL beverages"],
            "Varun Beverages": ["Varun Beverages India", "Varun Pepsi", "Varun FMCG", "Varun beverages"],
            "Emami": ["Emami India", "Emami FMCG", "Emami skincare", "Emami ayurveda"],
            "Jyothy Labs": ["Jyothy Labs India", "Jyothy FMCG", "Jyothy detergents", "Jyothy consumer"],
            "Tata Consumer Products": ["Tata Consumer India", "Tata FMCG", "Tata tea", "Tata foods"],
            "Patanjali Foods": ["Patanjali Foods India", "Patanjali FMCG", "Patanjali ayurveda", "Patanjali edible oils"],
            "Radico Khaitan": ["Radico Khaitan India", "Radico liquor", "Radico FMCG", "Radico beverages"]
        },
        "newsapi_keywords": [
            "FMCG India", "Hindustan Unilever", "ITC India", "Nestle India", "Britannia",
            "Dabur India", "Godrej Consumer", "Colgate-Palmolive India", "Marico", "Emami",
            "FMCG sales", "rural consumption", "FMCG marketing", "FMCG distribution", "FMCG brands",
            "consumer goods", "FMCG stocks", "FMCG e-commerce", "FMCG growth", "FMCG innovation",
            "FMCG packaging", "FMCG exports"
        ]
    },
    "Nifty Consumer Durables": {
        "stocks": {
            "Havells India": ["Havells India", "Havells electricals", "Havells appliances", "Havells lighting"],
            "Voltas": ["Voltas India", "Voltas AC", "Voltas appliances", "Voltas cooling"],
            "Whirlpool of India": ["Whirlpool India", "Whirlpool appliances", "Whirlpool washing machines", "Whirlpool refrigerators"],
            "Crompton Greaves Consumer": ["Crompton Greaves India", "Crompton appliances", "Crompton fans", "Crompton lighting"],
            "Bajaj Electricals": ["Bajaj Electricals India", "Bajaj appliances", "Bajaj lighting", "Bajaj consumer"],
            "Blue Star": ["Blue Star India", "Blue Star AC", "Blue Star cooling", "Blue Star appliances"],
            "V-Guard Industries": ["V-Guard India", "V-Guard electricals", "V-Guard stabilizers", "V-Guard appliances"],
            "Symphony": ["Symphony India", "Symphony coolers", "Symphony appliances", "Symphony consumer"],
            "TTK Prestige": ["TTK Prestige India", "TTK kitchen appliances", "TTK cookware", "TTK consumer"],
            "Orient Electric": ["Orient Electric India", "Orient fans", "Orient appliances", "Orient lighting"],
            "Dixon Technologies": ["Dixon Tech India", "Dixon electronics", "Dixon manufacturing", "Dixon consumer"],
            "Amber Enterprises": ["Amber Enterprises India", "Amber AC", "Amber appliances", "Amber manufacturing"],
            "Polycab India": ["Polycab India", "Polycab cables", "Polycab electricals", "Polycab consumer"],
            "Relaxo Footwears": ["Relaxo India", "Relaxo footwear", "Relaxo consumer", "Relaxo shoes"],
            "Century Plyboards": ["Century Ply India", "Century plywood", "Century consumer", "Century furniture"]
        },
        "newsapi_keywords": [
            "Consumer durables India", "Havells India", "Voltas", "Whirlpool India", "Crompton Greaves",
            "Bajaj Electricals", "Symphony India", "V-Guard Industries", "Blue Star India", "TTK Prestige",
            "home appliances", "consumer electronics", "durables sales", "smart appliances",
            "durables market", "durables exports", "durables innovation", "durables technology",
            "durables demand", "durables retail", "durables financing"
        ]
    },
    "Nifty Financial Services": {
        "stocks": {
            "Bajaj Finance": ["Bajaj Finance India", "Bajaj lending", "Bajaj fintech", "Bajaj consumer finance"],
            "HDFC Life Insurance": ["HDFC Life India", "HDFC insurance", "HDFC Life policies", "HDFC Life digital"],
            "SBI Life Insurance": ["SBI Life India", "SBI insurance", "SBI Life policies", "SBI Life digital"],
            "ICICI Prudential Life": ["ICICI Pru Life", "ICICI insurance", "ICICI Pru policies", "ICICI Pru digital"],
            "Shriram Finance": ["Shriram Finance India", "Shriram lending", "Shriram NBFC", "Shriram consumer"],
            "Cholamandalam Investment": ["Chola Finance India", "Cholamandalam NBFC", "Chola lending", "Chola consumer"],
            "Power Finance Corporation": ["PFC India", "Power Finance PSU", "PFC lending", "PFC infrastructure"],
            "REC Limited": ["REC India", "REC PSU", "REC lending", "REC infrastructure"],
            "Muthoot Finance": ["Muthoot Finance India", "Muthoot gold loans", "Muthoot NBFC", "Muthoot consumer"],
            "Bajaj Finserv": ["Bajaj Finserv India", "Bajaj financial services", "Bajaj fintech", "Bajaj consumer"],
            "LIC Housing Finance": ["LIC Housing India", "LIC home loans", "LIC housing NBFC", "LIC housing consumer"],
            "Aditya Birla Capital": ["Aditya Birla Capital India", "AB Capital NBFC", "AB Capital lending", "AB Capital consumer"],
            "Max Financial Services": ["Max Financial India", "Max insurance", "Max Life policies", "Max digital"],
            "Piramal Enterprises": ["Piramal Enterprises India", "Piramal NBFC", "Piramal lending", "Piramal consumer"],
            "L&T Finance Holdings": ["L&T Finance India", "L&T NBFC", "L&T lending", "L&T consumer"]
        },
        "newsapi_keywords": [
            "Financial services India", "Bajaj Finance", "HDFC Life", "SBI Life Insurance",
            "Shriram Finance", "Cholamandalam Finance", "ICICI Prudential", "Power Finance", "REC Limited",
            "Muthoot Finance", "NBFC India", "insurance India", "SEBI", "fintech India",
            "digital finance", "mutual funds India", "financial stocks", "financial inclusion",
            "financial market", "financial services growth", "financial innovation"
        ]
    },
    "Nifty Media": {
        "stocks": {
            "Zee Entertainment": ["Zee Entertainment India", "Zee media", "Zee OTT", "Zee television"],
            "Sun TV Network": ["Sun TV India", "Sun media", "Sun television", "Sun regional"],
            "PVR Inox": ["PVR Inox India", "PVR cinemas", "Inox movies", "PVR media"],
            "Dish TV India": ["Dish TV India", "Dish media", "Dish DTH", "Dish television"],
            "Network18 Media": ["Network18 India", "Network18 news", "Network18 media", "Network18 OTT"],
            "TV Today Network": ["TV Today India", "TV Today news", "TV Today media", "TV Today television"],
            "Jagran Prakashan": ["Jagran India", "Jagran print", "Jagran media", "Jagran news"],
            "DB Corp": ["DB Corp India", "DB media", "DB print", "DB news"],
            "Nazara Technologies": ["Nazara India", "Nazara gaming", "Nazara media", "Nazara digital"],
            "Saregama India": ["Saregama India", "Saregama music", "Saregama media", "Saregama digital"],
            "Hathway Cable": ["Hathway India", "Hathway cable", "Hathway media", "Hathway broadband"],
            "Tips Industries": ["Tips India", "Tips music", "Tips media", "Tips entertainment"],
            "Balaji Telefilms": ["Balaji Telefilms India", "Balaji media", "Balaji TV", "Balaji OTT"],
            "Prime Focus": ["Prime Focus India", "Prime media", "Prime VFX", "Prime entertainment"],
            "NDTV": ["NDTV India", "NDTV news", "NDTV media", "NDTV digital"]
        },
        "newsapi_keywords": [
            "Media India", "Zee Entertainment", "Sun TV Network", "PVR Inox", "Dish TV",
            "Network18", "TV Today Network", "Jagran Prakashan", "DB Corp", "Hathway Cable",
            "digital media", "OTT India", "media advertising", "TRAI", "media consumption",
            "broadcasting India", "print media", "media stocks", "media growth", "media innovation",
            "media technology", "media market"
        ]
    },
    "Nifty Metal": {
        "stocks": {
            "Tata Steel": ["Tata Steel India", "Tata steel", "Tata metal", "Tata manufacturing"],
            "JSW Steel": ["JSW Steel India", "JSW metal", "JSW manufacturing", "JSW steel production"],
            "Hindalco Industries": ["Hindalco India", "Hindalco aluminium", "Hindalco metal", "Hindalco manufacturing"],
            "Vedanta": ["Vedanta India", "Vedanta metals", "Vedanta mining", "Vedanta aluminium"],
            "SAIL": ["SAIL India", "Steel Authority India", "SAIL metal", "SAIL steel"],
            "NALCO": ["NALCO India", "National Aluminium", "NALCO metal", "NALCO manufacturing"],
            "Jindal Steel & Power": ["Jindal Steel India", "Jindal metal", "Jindal power", "Jindal manufacturing"],
            "APL Apollo Tubes": ["APL Apollo India", "APL tubes", "APL metal", "APL manufacturing"],
            "Ratnamani Metals": ["Ratnamani Metals India", "Ratnamani pipes", "Ratnamani metal", "Ratnamani manufacturing"],
            "Hindustan Zinc": ["Hindustan Zinc India", "Hindustan metal", "Hindustan zinc mining", "Hindustan manufacturing"],
            "NMDC": ["NMDC India", "NMDC mining", "NMDC metal", "NMDC iron ore"],
            "Welspun Corp": ["Welspun Corp India", "Welspun pipes", "Welspun metal", "Welspun manufacturing"],
            "JSL Stainless": ["JSL Stainless India", "JSL steel", "JSL metal", "JSL manufacturing"],
            "Hindustan Copper": ["Hindustan Copper India", "Hindustan metal", "Hindustan copper mining", "Hindustan manufacturing"],
            "MOIL": ["MOIL India", "MOIL manganese", "MOIL metal", "MOIL mining"]
        },
        "newsapi_keywords": [
            "Metals India", "Tata Steel", "JSW Steel", "Hindalco", "Vedanta", "SAIL",
            "NMDC", "Jindal Steel", "APL Apollo Tubes", "Ratnamani Metals", "steel production",
            "aluminium India", "mining India", "metal prices", "metal exports", "metal stocks",
            "metal demand", "metal market", "metal innovation", "metal technology",
            "metal sustainability"
        ]
    },
    "Nifty PSU Bank": {
        "stocks": {
            "SBI": ["State Bank of India", "SBI banking", "SBI PSU", "SBI digital"],
            "Bank of Baroda": ["Bank of Baroda India", "BOB PSU", "BOB banking", "BOB digital"],
            "PNB": ["Punjab National Bank", "PNB PSU", "PNB banking", "PNB digital"],
            "Canara Bank": ["Canara Bank India", "Canara PSU", "Canara banking", "Canara digital"],
            "Union Bank of India": ["Union Bank India", "Union PSU", "Union banking", "Union digital"],
            "Indian Bank": ["Indian Bank India", "Indian PSU", "Indian banking", "Indian digital"],
            "Bank of India": ["Bank of India PSU", "BOI banking", "BOI digital", "BOI PSU"],
            "Central Bank of India": ["Central Bank India", "Central PSU", "Central banking", "Central digital"],
            "UCO Bank": ["UCO Bank India", "UCO PSU", "UCO banking", "UCO digital"],
            "Indian Overseas Bank": ["IOB India", "IOB PSU", "IOB banking", "IOB digital"],
            "Maharashtra Bank": ["Bank of Maharashtra", "BOM PSU", "BOM banking", "BOM digital"],
            "Punjab & Sind Bank": ["Punjab & Sind Bank", "PSB PSU", "PSB banking", "PSB digital"],
            "J&K Bank": ["J&K Bank India", "J&K PSU", "J&K banking", "J&K digital"], # Note: J&K Bank is not a typical central PSU but often grouped here
            "IDBI Bank": ["IDBI Bank India", "IDBI PSU", "IDBI banking", "IDBI digital"] # Often considered PSU-like due to LIC ownership
        },
        "newsapi_keywords": [
            "PSU banks India", "State Bank of India", "Bank of Baroda", "Punjab National Bank",
            "Canara Bank", "Union Bank of India", "Indian Bank", "Bank of India", "Central Bank",
            "UCO Bank", "RBI", "NPA PSU banks", "PSU bank reforms", "PSU bank mergers",
            "PSU bank stocks", "PSU bank loans", "PSU bank deposits", "PSU bank growth",
            "PSU bank technology", "PSU bank earnings", "PSU bank recovery"
        ]
    },
    "Nifty Private Bank": {
        "stocks": {
            "HDFC Bank": ["HDFC Bank India", "HDFC private banking", "HDFC digital", "HDFC loans"],
            "ICICI Bank": ["ICICI Bank India", "ICICI private banking", "ICICI digital", "ICICI fintech"],
            "Axis Bank": ["Axis Bank India", "Axis private banking", "Axis digital", "Axis fintech"],
            "Kotak Mahindra Bank": ["Kotak Bank", "Kotak private banking", "Kotak digital", "Kotak wealth"],
            "IndusInd Bank": ["IndusInd Bank India", "IndusInd private banking", "IndusInd digital", "IndusInd loans"],
            "Yes Bank": ["Yes Bank India", "Yes private banking", "Yes digital", "Yes recovery"],
            "IDFC First Bank": ["IDFC First Bank", "IDFC private banking", "IDFC digital", "IDFC fintech"],
            "Federal Bank": ["Federal Bank India", "Federal private banking", "Federal digital", "Federal loans"],
            "Bandhan Bank": ["Bandhan Bank India", "Bandhan microfinance", "Bandhan private banking", "Bandhan digital"],
            "RBL Bank": ["RBL Bank India", "RBL private banking", "RBL digital", "RBL fintech"],
            "City Union Bank": ["City Union Bank", "CUB private banking", "CUB digital", "CUB loans"],
            "Karur Vysya Bank": ["Karur Vysya Bank", "KVB private banking", "KVB digital", "KVB loans"],
            "DCB Bank": ["DCB Bank India", "DCB private banking", "DCB digital", "DCB fintech"],
            "Equitas Small Finance Bank": ["Equitas Bank", "Equitas private banking", "Equitas digital", "Equitas microfinance"],
            "AU Small Finance Bank": ["AU Bank", "AU private banking", "AU digital", "AU fintech"]
        },
        "newsapi_keywords": [
            "Private banks India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank",
            "IndusInd Bank", "Yes Bank", "RBL Bank", "Federal Bank", "Bandhan Bank", "RBI",
            "private bank loans", "digital banking", "fintech India", "private bank stocks",
            "private bank deposits", "private bank growth", "private bank technology",
            "private bank earnings", "private bank reforms", "private bank market"
        ]
    },
    "Nifty Realty": {
        "stocks": {
            "DLF": ["DLF India", "DLF real estate", "DLF housing", "DLF commercial"],
            "Godrej Properties": ["Godrej Properties India", "Godrej realty", "Godrej housing", "Godrej commercial"],
            "Oberoi Realty": ["Oberoi Realty India", "Oberoi housing", "Oberoi commercial", "Oberoi real estate"],
            "Prestige Estates": ["Prestige Estates India", "Prestige realty", "Prestige housing", "Prestige commercial"],
            "Brigade Enterprises": ["Brigade Enterprises India", "Brigade realty", "Brigade housing", "Brigade commercial"],
            "Sobha": ["Sobha India", "Sobha real estate", "Sobha housing", "Sobha commercial"],
            "Phoenix Mills": ["Phoenix Mills India", "Phoenix realty", "Phoenix malls", "Phoenix commercial"],
            "Macrotech Developers": ["Macrotech India", "Lodha realty", "Lodha housing", "Lodha commercial"],
            "Sunteck Realty": ["Sunteck Realty India", "Sunteck housing", "Sunteck commercial", "Sunteck real estate"],
            "Mahindra Lifespace": ["Mahindra Lifespace India", "Mahindra realty", "Mahindra housing", "Mahindra commercial"],
            "Kolte Patil Developers": ["Kolte Patil India", "Kolte realty", "Kolte housing", "Kolte commercial"],
            "Puravankara": ["Puravankara India", "Puravankara realty", "Puravankara housing", "Puravankara commercial"],
            "Anant Raj": ["Anant Raj India", "Anant real estate", "Anant housing", "Anant commercial"],
            "Indiabulls Real Estate": ["Indiabulls Real Estate India", "Indiabulls realty", "Indiabulls housing", "Indiabulls commercial"],
            "NBCC India": ["NBCC India", "NBCC realty", "NBCC construction", "NBCC PSU"] # Also in CPSE/PSE
        },
        "newsapi_keywords": [
            "Real estate India", "DLF", "Godrej Properties", "Oberoi Realty", "Prestige Estates",
            "Brigade Enterprises", "Sobha Limited", "Phoenix Mills", "Macrotech Developers",
            "Sunteck Realty", "RERA India", "housing India", "commercial realty", "realty prices",
            "realty stocks", "realty demand", "realty market", "realty financing", "realty growth",
            "realty innovation", "realty technology"
        ]
    },
    "Nifty Commodities": { # This is a broad sector, stocks might overlap with others like Metal/Cement
        "stocks": {
            "UltraTech Cement": ["UltraTech Cement India", "UltraTech cement", "UltraTech construction", "UltraTech manufacturing"],
            "Shree Cement": ["Shree Cement India", "Shree cement", "Shree construction", "Shree manufacturing"],
            "Asian Paints": ["Asian Paints India", "Asian paints", "Asian coatings", "Asian consumer"],
            "Grasim Industries": ["Grasim India", "Grasim cement", "Grasim VSF", "Grasim chemicals"],
            "Pidilite Industries": ["Pidilite India", "Pidilite adhesives", "Pidilite chemicals", "Pidilite consumer"],
            "Ambuja Cements": ["Ambuja Cements India", "Ambuja cement", "Ambuja construction", "Ambuja manufacturing"],
            "ACC": ["ACC India", "ACC cement", "ACC construction", "ACC manufacturing"],
            "Tata Chemicals": ["Tata Chemicals India", "Tata chemicals", "Tata soda ash", "Tata salt"],
            "UPL": ["UPL India", "UPL agrochemicals", "UPL chemicals", "UPL agriculture"],
            "Coromandel International": ["Coromandel India", "Coromandel fertilizers", "Coromandel agro", "Coromandel chemicals"],
            "Deepak Nitrite": ["Deepak Nitrite India", "Deepak chemicals", "Deepak specialty", "Deepak manufacturing"],
            "SRF": ["SRF India", "SRF chemicals", "SRF technical textiles", "SRF packaging"],
            "Gujarat Fluorochemicals": ["Gujarat Fluorochemicals India", "GFL chemicals", "GFL fluorine", "GFL specialty"],
            "Kansai Nerolac": ["Kansai Nerolac India", "Nerolac paints", "Nerolac coatings", "Nerolac industrial"],
            "Berger Paints": ["Berger Paints India", "Berger paints", "Berger coatings", "Berger decorative"]
        },
        "newsapi_keywords": [
            "Commodities India", "UltraTech Cement", "Shree Cement", "Pidilite Industries",
            "Asian Paints", "Grasim Industries", "Ambuja Cements", "ACC Limited", "Tata Chemicals",
            "UPL", "cement industry", "chemicals India", "paints India", "agrochemicals India",
            "fertilizers India", "commodities prices", "commodities exports", "commodities stocks"
        ]
    },
    "Nifty Energy": {
        "stocks": {
            "Reliance Industries": ["Reliance Industries India", "Reliance energy", "Reliance oil", "Reliance renewables"],
            "NTPC": ["NTPC India", "NTPC power", "NTPC energy", "NTPC renewables"],
            "Power Grid Corporation": ["Power Grid India", "Power Grid energy", "Power Grid transmission", "Power Grid PSU"],
            "Adani Green Energy": ["Adani Green India", "Adani renewables", "Adani energy", "Adani solar"],
            "Tata Power": ["Tata Power India", "Tata energy", "Tata renewables", "Tata power generation"],
            "Adani Power": ["Adani Power India", "Adani energy", "Adani power generation", "Adani thermal"],
            "JSW Energy": ["JSW Energy India", "JSW power", "JSW renewables", "JSW energy generation"],
            "NHPC": ["NHPC India", "NHPC hydro", "NHPC energy", "NHPC PSU"],
            "Torrent Power": ["Torrent Power India", "Torrent energy", "Torrent power generation", "Torrent renewables"],
            "SJVN": ["SJVN India", "SJVN hydro", "SJVN energy", "SJVN PSU"],
            "Indian Oil Corporation": ["IOC India", "Indian Oil energy", "IOC refining", "IOC oil"], # Also in Oil&Gas, PSE
            "BPCL": ["BPCL India", "BPCL energy", "BPCL refining", "BPCL oil"], # Also in Oil&Gas, PSE
            "GAIL India": ["GAIL India", "GAIL energy", "GAIL gas", "GAIL pipelines"] # Also in Oil&Gas, PSE
        },
        "newsapi_keywords": [
            "Energy India", "Reliance Industries", "NTPC", "Power Grid", "Adani Green Energy",
            "Tata Power", "Adani Power", "JSW Energy", "NHPC", "SJVN", "renewable energy",
            "solar energy", "wind energy", "power generation", "electricity India",
            "energy policy", "energy stocks", "energy demand", "energy market", "energy transition"
        ]
    },
    "Nifty Infrastructure": {
        "stocks": {
            "Larsen & Toubro": ["L&T India", "Larsen & Toubro", "L&T infrastructure", "L&T construction"],
            "Adani Ports and SEZ": ["Adani Ports India", "Adani ports", "Adani infrastructure", "Adani SEZ"],
            "GMR Airports Infrastructure": ["GMR Airports India", "GMR infrastructure", "GMR airports", "GMR construction"],
            "IRB Infrastructure": ["IRB Infra India", "IRB infrastructure", "IRB roads", "IRB construction"],
            "KNR Constructions": ["KNR Constructions India", "KNR infrastructure", "KNR roads", "KNR construction"],
            "PNC Infratech": ["PNC Infratech India", "PNC infrastructure", "PNC roads", "PNC construction"],
            "NCC": ["NCC India", "NCC infrastructure", "NCC construction", "NCC roads"],
            "Dilip Buildcon": ["Dilip Buildcon India", "Dilip infrastructure", "Dilip roads", "Dilip construction"],
            "Ashoka Buildcon": ["Ashoka Buildcon India", "Ashoka infrastructure", "Ashoka roads", "Ashoka construction"],
            "GR Infraprojects": ["GR Infra India", "GR infrastructure", "GR roads", "GR construction"],
            "HG Infra Engineering": ["HG Infra India", "HG infrastructure", "HG roads", "HG construction"],
            "Power Grid Corporation": ["Power Grid India", "Power Grid infrastructure", "Power Grid transmission", "Power Grid energy"], # Also in Energy, PSE
            "NTPC": ["NTPC India", "NTPC infrastructure", "NTPC power projects", "NTPC energy"], # Also in Energy, PSE
            "Container Corporation": ["Concor India", "Concor infrastructure", "Concor logistics", "Concor transport"] # Also in PSE, CPSE
        },
        "newsapi_keywords": [
            "Infrastructure India", "Larsen & Toubro", "Adani Ports", "GMR Infrastructure",
            "IRB Infrastructure", "KNR Constructions", "PNC Infratech", "NCC Limited",
            "Dilip Buildcon", "Ashoka Buildcon", "roads India", "airports India", "ports India",
            "railways India", "construction India", "urban infrastructure", "smart cities",
            "infrastructure financing", "infrastructure stocks", "infrastructure projects"
        ]
    },
    "Nifty PSE": { # Public Sector Enterprises
        "stocks": {
            "ONGC": ["ONGC India", "ONGC oil", "ONGC exploration", "ONGC PSU"],
            "Coal India": ["Coal India PSU", "Coal India mining", "Coal India production", "Coal India energy"],
            "BHEL": ["BHEL India", "BHEL PSU", "BHEL power equipment", "BHEL manufacturing"],
            "GAIL India": ["GAIL India PSU", "GAIL gas", "GAIL pipelines", "GAIL energy"],
            "IOC": ["Indian Oil Corporation", "IOC PSU", "IOC oil", "IOC refining"],
            "BPCL": ["BPCL India", "BPCL PSU", "BPCL oil", "BPCL refining"],
            "HPCL": ["HPCL India", "HPCL PSU", "HPCL oil", "HPCL refining"],
            "Power Finance Corporation": ["PFC India", "PFC PSU", "PFC lending", "PFC power sector"],
            "REC Limited": ["REC India", "REC PSU", "REC lending", "REC power sector"],
            "NTPC": ["NTPC India", "NTPC PSU", "NTPC power", "NTPC renewables"],
            "Power Grid Corporation": ["Power Grid India", "Power Grid PSU", "Power Grid transmission", "Power Grid energy"],
            "Container Corporation": ["Concor India", "Concor PSU", "Concor logistics", "Concor transport"],
            "Bharat Electronics": ["BEL India", "BEL PSU", "BEL defence", "BEL electronics"],
            "NBCC India": ["NBCC India", "NBCC PSU", "NBCC construction", "NBCC real estate"],
            "Oil India": ["Oil India PSU", "Oil India exploration", "Oil India energy", "Oil India oil"],
            "Hindustan Aeronautics": ["HAL India", "HAL PSU", "HAL aerospace", "HAL defence"]
        },
        "newsapi_keywords": [
            "PSE India", "Public Sector Enterprises India", "ONGC", "Coal India", "BHEL", "GAIL India", "IOC", "BPCL", "HPCL",
            "Power Finance Corporation", "REC Limited", "NTPC", "Power Grid", "Container Corporation", "BEL", "NBCC", "Oil India", "HAL",
            "PSU disinvestment", "PSE reforms", "PSE stocks", "PSE earnings", "government companies India"
        ]
    },
    "Nifty Oil & Gas": {
        "stocks": {
            "Reliance Industries": ["Reliance Industries India", "Reliance oil", "Reliance gas", "Reliance petrochemicals"],
            "ONGC": ["ONGC India", "ONGC oil", "ONGC gas", "ONGC exploration"],
            "Indian Oil Corporation": ["IOC India", "Indian Oil", "IOC oil", "IOC refining"],
            "BPCL": ["BPCL India", "Bharat Petroleum", "BPCL oil", "BPCL refining"],
            "HPCL": ["HPCL India", "Hindustan Petroleum", "HPCL oil", "HPCL refining"],
            "GAIL India": ["GAIL India", "GAIL gas", "GAIL pipelines", "GAIL natural gas"],
            "Oil India": ["Oil India", "Oil India exploration", "Oil India gas", "Oil India production"],
            "Petronet LNG": ["Petronet LNG India", "Petronet gas", "Petronet LNG terminal", "Petronet imports"],
            "Indraprastha Gas": ["IGL India", "Indraprastha Gas", "IGL gas distribution", "IGL CNG"],
            "Mahanagar Gas": ["Mahanagar Gas India", "MGL gas", "MGL distribution", "MGL CNG"],
            "Gujarat Gas": ["Gujarat Gas India", "Gujarat gas distribution", "Gujarat PNG", "Gujarat gas network"],
            "Adani Total Gas": ["Adani Total Gas India", "Adani gas", "Adani CNG", "Adani PNG"],
            "Castrol India": ["Castrol India", "Castrol lubricants", "Castrol oil products", "Castrol automotive"],
            "Gulf Oil Lubricants": ["Gulf Oil India", "Gulf lubricants", "Gulf oil products", "Gulf automotive"],
            "Aegis Logistics": ["Aegis Logistics India", "Aegis gas logistics", "Aegis terminals", "Aegis LPG"]
        },
        "newsapi_keywords": [
            "Oil and gas India", "Reliance Industries", "ONGC", "Indian Oil", "BPCL", "HPCL",
            "GAIL India", "Oil India", "Petronet LNG", "IGL", "MGL", "Gujarat Gas",
            "oil exploration", "gas distribution", "refining India", "petrochemicals India", "LNG India",
            "CNG India", "oil prices", "gas prices", "oil and gas stocks", "energy sector India"
        ]
    },
    "Nifty Healthcare": { # As distinct from Nifty Pharma, this focuses more on service providers
        "stocks": {
            "Apollo Hospitals": ["Apollo Hospitals India", "Apollo healthcare services", "Apollo medical", "Apollo clinics"],
            "Fortis Healthcare": ["Fortis Healthcare India", "Fortis hospitals", "Fortis medical services", "Fortis diagnostics"],
            "Max Healthcare": ["Max Healthcare India", "Max hospitals", "Max medical services", "Max patient care"],
            "Metropolis Healthcare": ["Metropolis India", "Metropolis diagnostics", "Metropolis labs", "Metropolis pathology"],
            "Dr Lal PathLabs": ["Dr Lal PathLabs India", "Dr Lal diagnostics", "Dr Lal labs", "Dr Lal pathology"],
            "Narayana Hrudayalaya": ["Narayana Hrudayalaya India", "Narayana hospitals", "Narayana cardiac care", "Narayana health city"],
            "Aster DM Healthcare": ["Aster DM India", "Aster hospitals", "Aster clinics", "Aster pharmacies"],
            "Thyrocare Technologies": ["Thyrocare India", "Thyrocare diagnostics", "Thyrocare wellness", "Thyrocare labs"],
            "Healthcare Global Enterprises": ["HCG Oncology India", "HCG cancer care", "HCG hospitals", "HCG specialty"],
            "Krishna Institute of Medical Sciences": ["KIMS Hospitals India", "KIMS medical services", "KIMS patient care", "KIMS multi-specialty"],
            "Global Health Ltd (Medanta)": ["Medanta India", "Medanta hospitals", "Medanta multi-specialty", "Medanta Gurugram"],
            "Rainbow Childrens Medicare": ["Rainbow Childrens Hospital India", "Rainbow pediatric care", "Rainbow womens health", "Rainbow multi-specialty"],
            "Kovai Medical Center": ["Kovai Medical India", "KMCH Coimbatore", "Kovai hospitals", "Kovai multi-specialty"],
            "Shalby Multi-specialty Hospitals": ["Shalby Hospitals India", "Shalby orthopedics", "Shalby multi-specialty", "Shalby joint replacement"],
            "Vijaya Diagnostic Centre": ["Vijaya Diagnostic India", "Vijaya diagnostics", "Vijaya imaging", "Vijaya pathology"]
        },
        "newsapi_keywords": [ # Keywords for the Healthcare SECTOR
            "Healthcare India", "Hospitals India", "Diagnostics India", "Medical services India", "Telemedicine India",
            "Apollo Hospitals", "Fortis Healthcare", "Max Healthcare", "Metropolis Healthcare", "Dr Lal PathLabs", # Key players for sector context
            "healthcare policy", "healthcare infrastructure", "medical tourism India", "health tech India",
            "patient care India", "hospital chains India", "diagnostic chains India", "healthcare investments"
        ]
    },
    "Nifty Midcap Liquid 15": { # This is an index of specific liquid midcap stocks, not a thematic sector
        "stocks": { # The stocks themselves are the primary focus
            "Ashok Leyland": ["Ashok Leyland India", "Ashok Leyland trucks", "Ashok Leyland commercial vehicles", "Ashok Leyland sales"],
            "Bharat Forge": ["Bharat Forge India", "Bharat Forge auto components", "Bharat Forge forging", "Bharat Forge defence"],
            "Container Corporation": ["Concor India", "Container Corporation of India", "Concor logistics", "Concor rail freight"],
            "Tata Power": ["Tata Power India", "Tata Power renewables", "Tata Power generation", "Tata Power distribution"],
            "Godrej Properties": ["Godrej Properties India", "Godrej Properties real estate", "Godrej Properties projects", "Godrej Properties sales"],
            "LTIMindtree": ["LTIMindtree India", "LTIMindtree IT services", "LTIMindtree digital", "LTIMindtree results"], # Also in IT
            "Muthoot Finance": ["Muthoot Finance India", "Muthoot Finance gold loans", "Muthoot Finance NBFC", "Muthoot Finance earnings"],
            "PI Industries": ["PI Industries India", "PI Industries agrochemicals", "PI Industries CSM", "PI Industries R&D"],
            "Vodafone Idea": ["Vodafone Idea India", "Vi India", "Vodafone Idea telecom", "Vodafone Idea 5G"],
            "Max Financial Services": ["Max Financial Services India", "Max Life Insurance", "Max Financial insurance", "Max Financial earnings"], # Also in Fin Services
            "Aarti Industries": ["Aarti Industries India", "Aarti Industries chemicals", "Aarti Industries specialty chemicals", "Aarti Industries results"],
            "Polycab India": ["Polycab India", "Polycab cables and wires", "Polycab FMEG", "Polycab earnings"],
            "Astral Ltd": ["Astral India", "Astral pipes", "Astral adhesives", "Astral results"],
            "Oberoi Realty": ["Oberoi Realty India", "Oberoi Realty real estate", "Oberoi Realty luxury", "Oberoi Realty projects"], # Also in Realty
            "Indian Hotels": ["Indian Hotels Company", "IHCL India", "Taj Hotels", "Indian Hotels hospitality"]
        },
        "newsapi_keywords": [ # Generic midcap terms, less effective than specific stock news for this index
            "Midcap India", "Indian midcap stocks", "midcap growth", "midcap earnings", "Nifty Midcap 150",
            "midcap investments", "midcap market trends", "emerging companies India"
            # For this index, fetching news per stock is more critical than broad "midcap" terms.
        ]
    },
    "Nifty CPSE": { # Central Public Sector Enterprises
        "stocks": {
            "NTPC": ["NTPC India", "NTPC CPSE", "NTPC power", "NTPC results"],
            "Power Grid Corporation": ["Power Grid India", "Power Grid CPSE", "Power Grid transmission", "Power Grid earnings"],
            "Oil India": ["Oil India CPSE", "Oil India exploration", "Oil India production", "Oil India results"],
            "NBCC India": ["NBCC India CPSE", "NBCC construction", "NBCC projects", "NBCC orders"],
            "BHEL": ["BHEL India CPSE", "Bharat Heavy Electricals", "BHEL power equipment", "BHEL orders"],
            "SAIL": ["SAIL India CPSE", "Steel Authority of India", "SAIL steel", "SAIL production"],
            "NMDC": ["NMDC India CPSE", "NMDC mining", "NMDC iron ore", "NMDC sales"],
            "Bharat Electronics": ["BEL India CPSE", "BEL defence", "BEL electronics", "BEL orders"],
            "Hindustan Aeronautics": ["HAL India CPSE", "HAL aerospace", "HAL defence", "HAL orders"],
            "Container Corporation": ["Concor India CPSE", "Concor logistics", "Concor freight", "Concor results"],
            "Cochin Shipyard": ["Cochin Shipyard India CPSE", "Cochin Shipyard shipbuilding", "Cochin Shipyard defence", "Cochin Shipyard orders"],
            "Mazagon Dock Shipbuilders": ["Mazagon Dock India CPSE", "MDL shipbuilding", "Mazagon Dock defence", "Mazagon Dock orders"],
            "Garden Reach Shipbuilders": ["Garden Reach Shipbuilders India CPSE", "GRSE shipbuilding", "GRSE defence", "GRSE orders"],
            "RITES Ltd": ["RITES India CPSE", "RITES infrastructure consultancy", "RITES railways", "RITES orders"],
            "Engineers India Ltd": ["Engineers India CPSE", "EIL consultancy", "EIL projects", "EIL oil and gas"]
        },
        "newsapi_keywords": [
            "CPSE India", "Central Public Sector Enterprises India", "NTPC", "Power Grid", "Oil India", "NBCC", "BHEL", # Key CPSEs
            "PSU stocks India", "government companies India", "CPSE disinvestment", "CPSE reforms",
            "CPSE earnings", "CPSE performance", "CPSE projects", "CPSE capex"
        ]
    },
    "Nifty Services Sector": { # Broad sector, overlaps with IT, Bank, Telecom etc.
        "stocks": {
            "Infosys": ["Infosys India", "Infosys services", "Infosys IT consulting", "Infosys digital services"], # IT
            "HDFC Bank": ["HDFC Bank India", "HDFC Bank financial services", "HDFC Bank banking", "HDFC Bank digital"], # Bank
            "Bharti Airtel": ["Bharti Airtel India", "Airtel telecom services", "Airtel mobile services", "Airtel broadband"], # Telecom
            "TCS": ["Tata Consultancy Services", "TCS IT services", "TCS consulting", "TCS digital solutions"], # IT
            "ICICI Bank": ["ICICI Bank India", "ICICI Bank financial services", "ICICI Bank banking", "ICICI Bank digital"], # Bank
            "Kotak Mahindra Bank": ["Kotak Mahindra Bank India", "Kotak Bank financial services", "Kotak Bank banking", "Kotak Bank wealth"], # Bank
            "Bajaj Finance": ["Bajaj Finance India", "Bajaj Finance lending services", "Bajaj Finance consumer finance", "Bajaj Finance NBFC"], # Financial Services
            "Reliance Industries": ["Reliance Industries services", "Reliance Jio telecom", "Reliance Retail", "Reliance digital services"], # Conglomerate with large services arm
            "Avenue Supermarts (DMart)": ["DMart India", "Avenue Supermarts retail services", "DMart supermarket", "DMart operations"], # Retail
            "Zomato": ["Zomato India", "Zomato food delivery services", "Zomato online platform", "Zomato quick commerce"], # Online Platform
            "IndusInd Bank": ["IndusInd Bank financial services", "IndusInd Bank banking", "IndusInd digital services"], # Bank
            "SBI Life Insurance": ["SBI Life Insurance services", "SBI Life policies", "SBI Life customer service"], # Financial Services
            "Tech Mahindra": ["Tech Mahindra IT services", "Tech Mahindra BPO", "Tech Mahindra consulting"], # IT
            "Adani Ports and SEZ": ["Adani Ports logistics services", "Adani Ports SEZ services", "Adani Ports operations"], # Infrastructure/Logistics Services
            "Apollo Hospitals": ["Apollo Hospitals healthcare services", "Apollo medical services", "Apollo patient care"] # Healthcare Services
        },
        "newsapi_keywords": [
            "Services sector India", "IT services India", "Financial services India", "Telecom services India", "Healthcare services India",
            "Logistics services India", "Retail services India", "Infosys", "HDFC Bank", "Bharti Airtel", "TCS", # Key players
            "Indian services PMI", "services growth India", "digital services India", "outsourcing India",
            "customer service India", "e-commerce services", "services economy", "services stocks"
        ]
    },
    "Nifty India Manufacturing": {
        "stocks": {
            "Reliance Industries": ["Reliance Industries manufacturing", "Reliance petrochemicals manufacturing", "Reliance refining", "Reliance polymers"], # Large manufacturing arm
            "Larsen & Toubro": ["L&T India manufacturing", "Larsen & Toubro heavy engineering", "L&T defence manufacturing", "L&T construction equipment"],
            "Tata Motors": ["Tata Motors manufacturing", "Tata Motors automotive manufacturing", "Tata Motors plants", "Tata Motors EV manufacturing"],
            "Mahindra & Mahindra": ["Mahindra & Mahindra manufacturing", "M&M automotive manufacturing", "M&M farm equipment manufacturing", "M&M plants"],
            "Sun Pharma": ["Sun Pharma manufacturing", "Sun Pharma drug manufacturing", "Sun Pharma API", "Sun Pharma plants"],
            "ITC Ltd": ["ITC manufacturing", "ITC FMCG manufacturing", "ITC paperboards manufacturing", "ITC packaging"],
            "JSW Steel": ["JSW Steel manufacturing", "JSW Steel production", "JSW Steel plants", "JSW Steel capacity"],
            "Tata Steel": ["Tata Steel manufacturing", "Tata Steel production", "Tata Steel plants", "Tata Steel capacity"],
            "Hindalco Industries": ["Hindalco manufacturing", "Hindalco aluminium manufacturing", "Hindalco copper", "Hindalco Novelis"],
            "UltraTech Cement": ["UltraTech Cement manufacturing", "UltraTech Cement production", "UltraTech Cement plants", "UltraTech grinding units"],
            "Maruti Suzuki": ["Maruti Suzuki manufacturing", "Maruti Suzuki automotive manufacturing", "Maruti Suzuki plants", "Maruti Suzuki production"],
            "Siemens India": ["Siemens India manufacturing", "Siemens industrial automation", "Siemens factory", "Siemens machinery"],
            "Cummins India": ["Cummins India manufacturing", "Cummins engines manufacturing", "Cummins power generation", "Cummins plants"],
            "ABB India": ["ABB India manufacturing", "ABB industrial automation", "ABB robotics", "ABB electrification"],
            "Bharat Electronics": ["BEL India manufacturing", "BEL defence electronics manufacturing", "BEL systems", "BEL radar"]
        },
        "newsapi_keywords": [
            "Manufacturing India", "Make in India initiative", "Industrial production India", "Factory output India",
            "Automotive manufacturing India", "Pharmaceutical manufacturing India", "Electronics manufacturing India",
            "Heavy engineering India", "Steel manufacturing India", "Cement manufacturing India",
            "Reliance Industries", "Larsen & Toubro", "Tata Motors", "Mahindra & Mahindra", "Sun Pharma", # Key players
            "PLI scheme India", "manufacturing PMI", "manufacturing exports", "manufacturing investments", "industrial corridors"
        ]
    }
}


NEWSAPI_INDIA_MARKET_KEYWORDS = ["India", "Indian market", "NSE", "BSE", "Indian economy"]

# The analyze_news_with_gemini function remains largely the same as your last version.
# The `analysis_target_name` will be the stock's name when called for a stock.
# The prompt's reference to '{analysis_target_name}' will then correctly refer to the stock.

def analyze_news_with_gemini(
    _api_key, articles_texts_list, analysis_target_name, date_range_str,
    custom_instructions="", append_log_func=None, target_type="sector" # New parameter
):
    log_msg_prefix = f"[Gemini][{analysis_target_name}]"
    
    def _log(message, level='info'):
        full_message = f"{log_msg_prefix} {message}"
        if level == 'error': logger.error(full_message)
        elif level == 'warning': logger.warning(full_message)
        else: logger.info(full_message)
        if append_log_func: append_log_func(message, level.upper())

    _log(f"Starting analysis for {target_type} '{analysis_target_name}' with {len(articles_texts_list)} articles for dates {date_range_str}.")

    if not _api_key or _api_key == "YOUR_GEMINI_API_KEY_HERE":
        err_msg = "Gemini API Key not provided or is a placeholder."
        _log(err_msg, 'error')
        return None, err_msg

    try:
        genai.configure(api_key=_api_key)
    except Exception as e:
        err_msg = f"Failed to configure Gemini API: {str(e)[:150]}"
        _log(err_msg, 'error')
        return None, err_msg

    MAX_TOTAL_CHARS_FOR_LLM = 25000 
    truncated_articles_texts_list = []; current_chars = 0; num_original_articles = len(articles_texts_list)
    for text in articles_texts_list:
        if current_chars + len(text) > MAX_TOTAL_CHARS_FOR_LLM and truncated_articles_texts_list: break
        text_to_add = text[:MAX_TOTAL_CHARS_FOR_LLM - current_chars]
        truncated_articles_texts_list.append(text_to_add); current_chars += len(text_to_add)
        if current_chars >= MAX_TOTAL_CHARS_FOR_LLM: break
    
    if len(truncated_articles_texts_list) < num_original_articles:
        warn_msg = f"Truncated input for '{analysis_target_name}': {num_original_articles} to {len(truncated_articles_texts_list)} articles ({current_chars} chars)."
        _log(warn_msg, 'warning')
    
    combined_text = "\n\n--- ARTICLE SEPARATOR ---\n\n".join(truncated_articles_texts_list)
    
    default_response_structure = { "summary": "N/A", "overall_sentiment": "Neutral", "sentiment_score_llm": 0.0, "sentiment_reason": "N/A", "key_themes": [], "potential_impact": "N/A", "key_companies_mentioned_context": [], "risks_identified": [], "opportunities_identified": []}

    if not combined_text.strip():
        _log(f"No news content for LLM analysis for '{analysis_target_name}' after potential truncation.")
        final_response = default_response_structure.copy()
        final_response["summary"] = f"No news content was available for LLM analysis for {analysis_target_name}."
        final_response["sentiment_reason"] = "No articles available or all were empty/irrelevant for the LLM."
        return final_response, None

    # Determine if we are analyzing a sector or a stock to tailor the prompt slightly
    # The `analysis_target_name` will be the stock name if target_type is "stock"
    # The prompt should inherently work, but we could add a specific instruction if needed.
    # For now, relying on `analysis_target_name` to correctly scope the analysis.

    prompt = f"""
    Analyze the following news articles concerning '{analysis_target_name}' (which is a {target_type}) in the Indian market, from the period '{date_range_str}'.
    Articles are concatenated and separated by '--- ARTICLE SEPARATOR ---'.

    --- NEWS CONTENT START ---
    {combined_text}
    --- NEWS CONTENT END ---

    {custom_instructions if custom_instructions else f"Focus on financial and market implications specifically for '{analysis_target_name}'. Be concise and objective."}

    Your task is to provide a structured analysis in JSON format. The JSON object must include the following keys:
    - "summary": A concise 2-3 sentence summary of the key news and developments for '{analysis_target_name}'. If no relevant news is found specific to '{analysis_target_name}', state that clearly.
    - "overall_sentiment": Classify the overall sentiment FOR '{analysis_target_name}'. Choose one: "Strongly Positive", "Positive", "Neutral", "Negative", "Strongly Negative". This should align with your "sentiment_score_llm".
    - "sentiment_score_llm": A float value representing the sentiment FOR '{analysis_target_name}'. Adhere to these ranges:
        - Strongly Positive: 0.6 to 1.0
        - Positive: 0.2 to 0.59
        - Neutral: -0.19 to 0.19
        - Negative: -0.59 to -0.2
        - Strongly Negative: -1.0 to -0.6
      GUIDANCE FOR NEUTRAL SCORES (apply this considering '{analysis_target_name}'):
      1. If the news contains a mix of positive and negative developments for '{analysis_target_name}', and they roughly balance out, assign a score near 0.0 (e.g., -0.05 to 0.05).
      2. If the news is predominantly factual without clear positive or negative sentiment cues *directly impacting '{analysis_target_name}'*, assign a score in the Neutral range.
      3. If the news primarily concerns broader market/sector trends that only *indirectly* relate to '{analysis_target_name}', its specific sentiment is likely Neutral. However, if the *overall tone* of these indirect news items is slightly positive (e.g. general market optimism), you can use a score like 0.1 to 0.19 for '{analysis_target_name}'. If the tone is slightly negative, use -0.1 to -0.19.
      4. If there is truly no relevant information specific to '{analysis_target_name}' or the information is entirely non-consequential, a score of 0.0 is appropriate.
      Your score should reflect the *net sentiment impact on '{analysis_target_name}'* based on the provided articles.
    - "sentiment_reason": A brief 1-sentence explanation for the assigned sentiment and score for '{analysis_target_name}'. If sentiment is Neutral due to indirect news or mixed signals, explain that.
    - "key_themes": A list of 2-3 dominant themes emerging from the news concerning '{analysis_target_name}'. If no relevant news, this can be an empty list or state "N/A due to lack of relevant news".
    - "potential_impact": A 1-sentence assessment of the potential impact on '{analysis_target_name}'. If no relevant news, state "N/A".
    - "key_companies_mentioned_context": If analyzing a SECTOR, list key companies. If analyzing a specific STOCK ('{analysis_target_name}'), this list can be broader entities or related companies mentioned. Provide brief context. Empty list if not applicable.
    - "risks_identified": A list of 1-2 potential risks for '{analysis_target_name}'. Each risk a short string. Empty list if none or no relevant news.
    - "opportunities_identified": A list of 1-2 potential opportunities for '{analysis_target_name}'. Each opportunity a short string. Empty list if none or no relevant news.

    Ensure the output is ONLY the JSON object, without any preceding or succeeding text, and no markdown formatting for the JSON block itself.
    """
    try:
        model_name = 'gemini-2.5-pro'
        _log(f"Using Gemini model: {model_name} for '{analysis_target_name}'", 'info')
        model = genai.GenerativeModel(model_name)
        generation_config = genai.types.GenerationConfig(temperature=0.3)
        response = model.generate_content(prompt, generation_config=generation_config)
        
        cleaned_response_text = ""
        if hasattr(response, 'text') and response.text: cleaned_response_text = response.text.strip()
        elif response.parts: cleaned_response_text = "".join(part.text for part in response.parts).strip()
        else: 
            _log(f"Gemini response for '{analysis_target_name}' is empty or in an unexpected format.", "error")
            raise ValueError("Gemini response is empty or in an unexpected format.")

        if cleaned_response_text.startswith("```json"): cleaned_response_text = cleaned_response_text[len("```json"):].strip()
        if cleaned_response_text.endswith("```"): cleaned_response_text = cleaned_response_text[:-len("```")].strip()
        
        json_start_index = cleaned_response_text.find('{'); json_end_index = cleaned_response_text.rfind('}')
        if json_start_index != -1 and json_end_index != -1 and json_end_index > json_start_index:
            cleaned_response_text = cleaned_response_text[json_start_index : json_end_index+1]
        else: 
            _log(f"Could not find valid JSON structure in response for '{analysis_target_name}': '{cleaned_response_text[:200]}...'", 'error')
            raise json.JSONDecodeError(f"Could not find valid JSON structure in response for {analysis_target_name}.", cleaned_response_text, 0)

        result = json.loads(cleaned_response_text)
        
        for key, default_value in default_response_structure.items():
            if key not in result:
                _log(f"Gemini response for '{analysis_target_name}' missing key '{key}'. Using default: {default_value}", 'warning')
                result[key] = default_value
            elif isinstance(default_value, list) and not isinstance(result.get(key), list):
                _log(f"Gemini response key '{key}' for '{analysis_target_name}' is not a list as expected. Defaulting to empty list.", 'warning')
                result[key] = []
            elif key == "sentiment_score_llm" and not isinstance(result.get(key), (float, int)):
                _log(f"Gemini response key 'sentiment_score_llm' for '{analysis_target_name}' is not a number. Defaulting to 0.0.", 'warning')
                result[key] = 0.0

        _log(f"Analysis successfully completed for '{analysis_target_name}'.")
        return result, None

    except json.JSONDecodeError as e:
        err_msg = f"Gemini JSON Decode Error for '{analysis_target_name}': {str(e)[:150]}. Response: '{cleaned_response_text[:200]}...'"
        _log(err_msg, 'error')
        return None, f"Gemini returned an invalid JSON for {analysis_target_name}. Please check server logs."
    except Exception as e:
        err_msg = f"Gemini Analysis Error for '{analysis_target_name}': {str(e)[:150]}"
        _log(f"{err_msg} - Full traceback on server.", 'error')
        logger.exception(f"{log_msg_prefix} Full Gemini Exception for {analysis_target_name}") 
        return None, f"Error during Gemini analysis for {analysis_target_name}: {str(e)[:100]}"

NEWSAPI_INDIA_MARKET_KEYWORDS = ["India", "Indian market", "NSE", "BSE", "Indian economy"]