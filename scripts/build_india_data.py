"""Generate All India States and Stations (Districts/Cities) for RMS Gate Entry.
Produces:
1. frontend/src/features/goods-slips/indiaData.ts
2. supabase/migrations/20261110000000_all_india_states_and_stations.sql
"""

import json
from pathlib import Path

# Complete mapping of 28 States + 8 Union Territories and all their stations / districts / key cities
INDIA_DATA = {
    "Andhra Pradesh": {
        "code": "AP",
        "stations": [
            "Alluri Sitharama Raju", "Anakapalli", "Anantapur", "Annamayya", "Bapatla",
            "Chittoor", "Dr. B.R. Ambedkar Konaseema", "East Godavari (Rajahmundry)", "Eluru",
            "Guntur", "Kakinada", "Krishna (Machilipatnam)", "Kurnool", "Nandyal",
            "NTR (Vijayawada)", "Palnadu", "Parvathipuram Manyam", "Prakasam (Ongole)",
            "Nellore", "Sri Sathya Sai (Puttaparthi)", "Srikakulam", "Tirupati",
            "Visakhapatnam", "Vizianagaram", "West Godavari (Bhimavaram)", "YSR Kadapa",
            "Adoni", "Hindupur", "Proddatur", "Tenali", "Guntakal", "Dharmavaram", "Gudivada"
        ]
    },
    "Arunachal Pradesh": {
        "code": "AR",
        "stations": [
            "Anjaw", "Changlang", "Dibang Valley", "East Kameng", "East Siang (Pasighat)",
            "Kamle", "Kra Daadi", "Kurung Kumey", "Lepa Rada", "Lohit (Tezu)", "Longding",
            "Lower Dibang Valley (Roing)", "Lower Siang", "Lower Subansiri (Ziro)", "Namsai",
            "Pakke Kessang", "Papum Pare (Itanagar / Naharlagun)", "Shi Yomi", "Siang",
            "Tawang", "Tirap (Khonsa)", "Upper Siang", "Upper Subansiri", "West Kameng (Bomdila)",
            "West Siang (Aalo)"
        ]
    },
    "Assam": {
        "code": "AS",
        "stations": [
            "Baksa", "Barpeta", "Biswanath", "Bongaigaon", "Cachar (Silchar)", "Charaideo",
            "Chirang", "Darrang", "Dhemaji", "Dhubri", "Dibrugarh", "Dima Hasao (Haflong)",
            "Goalpara", "Golaghat", "Hailakandi", "Hojai", "Jorhat", "Kamrup Metropolitan (Guwahati)",
            "Kamrup", "Karbi Anglong (Diphu)", "Karimganj", "Kokrajhar", "Lakhimpur (North Lakhimpur)",
            "Majuli", "Morigaon", "Nagaon", "Nalbari", "Sivasagar", "Sonitpur (Tezpur)",
            "South Salmara-Mankachar", "Tinsukia", "Udalguri", "West Karbi Anglong", "Lumding"
        ]
    },
    "Bihar": {
        "code": "BR",
        "stations": [
            "Araria", "Arwal", "Aurangabad", "Banka", "Begusarai", "Bhagalpur", "Bhojpur (Arrah)",
            "Buxar", "Darbhanga", "East Champaran (Motihari)", "Gaya", "Gopalganj", "Jamui",
            "Jehanabad", "Kaimur (Bhabua)", "Katihar", "Khagaria", "Kishanganj", "Lakhisarai",
            "Madhepura", "Madhubani", "Munger", "Muzaffarpur", "Nalanda (Bihar Sharif)", "Nawada",
            "Patna", "Purnia", "Rohtas (Sasaram / Dehri)", "Saharsa", "Samastipur", "Saran (Chhapra)",
            "Sheikhpura", "Sheohar", "Sitamarhi", "Siwan", "Supaul", "Vaishali (Hajipur)",
            "West Champaran (Bettiah)", "Danapur", "Bagaha"
        ]
    },
    "Chhattisgarh": {
        "code": "CG",
        "stations": [
            "Balod", "Baloda Bazar", "Balrampur-Ramanujganj", "Bastar (Jagdalpur)", "Bemetara",
            "Bijapur", "Bilaspur", "Dantewada", "Dhamtari", "Durg (Bhilai)", "Gariaband",
            "Gaurela-Pendra-Marwahi", "Janjgir-Champa", "Jashpur", "Kabirdham (Kawardha)",
            "Kanker", "Khairagarh-Chhuikhadan-Gandai", "Kondagaon", "Korba", "Korea",
            "Mahasamund", "Manendragarh-Chirmiri-Bharatpur", "Mohla-Manpur-Ambagarh Chowki",
            "Mungeli", "Narayanpur", "Raigarh", "Raipur", "Rajnandgaon", "Sarangarh-Bilaigarh",
            "Sakti", "Sukma", "Surajpur", "Surguja (Ambikapur)"
        ]
    },
    "Goa": {
        "code": "GA",
        "stations": [
            "North Goa (Panaji)", "Mapusa", "Bicholim", "Pernem", "Valpoi",
            "South Goa (Margao)", "Vasco da Gama", "Ponda", "Curchorem", "Canacona",
            "Quepem", "Sanguem"
        ]
    },
    "Gujarat": {
        "code": "GJ",
        "stations": [
            "Ahmedabad", "Amreli", "Anand", "Aravalli (Modasa)", "Banaskantha (Palanpur)",
            "Bharuch", "Bhavnagar", "Botad", "Chhota Udaipur", "Dahod", "Dang (Ahwa)",
            "Devbhumi Dwarka", "Gandhinagar", "Gir Somnath (Veraval)", "Jamnagar", "Junagadh",
            "Kheda (Nadiad)", "Kutch (Bhuj)", "Mahisagar (Lunawada)", "Mehsana", "Morbi",
            "Narmada (Rajpipla)", "Navsari", "Panchmahal (Godhra)", "Patan", "Porbandar",
            "Rajkot", "Sabarkantha (Himmatnagar)", "Surat", "Surendranagar", "Tapi (Vyara)",
            "Vadodara", "Valsad", "Vapi", "Ankleshwar", "Gandhidham", "Deesa", "Jetpur"
        ]
    },
    "Haryana": {
        "code": "HR",
        "stations": [
            "Ambala", "Bhiwani", "Charkhi Dadri", "Faridabad", "Fatehabad", "Gurugram",
            "Hisar", "Jhajjar (Bahadurgarh)", "Jind", "Kaithal", "Karnal",
            "Kurukshetra (Thanesar)", "Mahendragarh (Narnaul)", "Nuh", "Palwal", "Panchkula",
            "Panipat", "Rewari", "Rohtak", "Sirsa", "Sonipat", "Yamunanagar (Jagadhri)"
        ]
    },
    "Himachal Pradesh": {
        "code": "HP",
        "stations": [
            "Bilaspur", "Chamba", "Hamirpur", "Kangra (Dharamshala)", "Kinnaur (Reckong Peo)",
            "Kullu (Manali)", "Lahaul and Spiti (Keylong)", "Mandi", "Shimla",
            "Sirmaur (Nahan)", "Solan (Baddi)", "Una", "Paonta Sahib", "Palampur"
        ]
    },
    "Jharkhand": {
        "code": "JH",
        "stations": [
            "Bokaro (Bokaro Steel City)", "Chatra", "Deoghar", "Dhanbad", "Dumka",
            "East Singhbhum (Jamshedpur)", "Garhwa", "Giridih", "Godda", "Gumla", "Hazaribagh",
            "Jamtara", "Khunti", "Koderma", "Latehar", "Lohardaga", "Pakur",
            "Palamu (Medininagar / Daltonganj)", "Ramgarh", "Ranchi", "Sahibganj",
            "Seraikela Kharsawan", "Simdega", "West Singhbhum (Chaibasa)", "Phusro"
        ]
    },
    "Karnataka": {
        "code": "KA",
        "stations": [
            "Bagalkote", "Ballari", "Belagavi", "Bengaluru Rural", "Bengaluru Urban",
            "Bidar", "Chamarajanagar", "Chikkaballapura", "Chikkamagaluru", "Chitradurga",
            "Dakshina Kannada (Mangaluru)", "Davanagere", "Dharwad (Hubballi-Dharwad)",
            "Gadag", "Hassan", "Haveri", "Kalaburagi (Gulbarga)", "Kodagu (Madikeri)",
            "Kolar", "Koppal", "Mandya", "Mysuru", "Raichur", "Ramanagara",
            "Shivamogga (Shimoga)", "Tumakuru (Tumkur)", "Udupi", "Uttara Kannada (Karwar)",
            "Vijayanagara (Hosapete)", "Vijayapura (Bijapur)", "Yadgir", "Bhadravati"
        ]
    },
    "Kerala": {
        "code": "KL",
        "stations": [
            "Alappuzha", "Ernakulam (Kochi)", "Idukki", "Kannur", "Kasaragod", "Kollam",
            "Kottayam", "Kozhikode", "Malappuram", "Palakkad", "Pathanamthitta",
            "Thiruvananthapuram", "Thrissur", "Wayanad (Kalpetta)"
        ]
    },
    "Madhya Pradesh": {
        "code": "MP",
        "stations": [
            "Agar Malwa", "Alirajpur", "Anuppur", "Ashoknagar", "Balaghat", "Barwani",
            "Betul", "Bhind", "Bhopal", "Burhanpur", "Chhatarpur", "Chhindwara", "Damoh",
            "Datia", "Dewas", "Dhar (Pithampur)", "Dindori", "Guna", "Gwalior", "Harda",
            "Hoshangabad (Narmadapuram)", "Indore", "Jabalpur", "Jhabua", "Katni",
            "Khandwa", "Khargone", "Maihar", "Mandla", "Mandsaur", "Morena", "Narsinghpur",
            "Neemuch", "Niwari", "Pandhurna", "Panna", "Raisen", "Rajgarh", "Ratlam",
            "Rewa", "Sagar", "Satna", "Sehore", "Seoni", "Shahdol", "Shajapur", "Sheopur",
            "Shivpuri", "Sidhi", "Singrauli", "Tikamgarh", "Ujjain", "Umaria", "Vidisha"
        ]
    },
    "Maharashtra": {
        "code": "MH",
        "stations": [
            "Ahmednagar", "Akola", "Amravati", "Chhatrapati Sambhajinagar (Aurangabad)", "Beed",
            "Bhandara", "Buldhana", "Chandrapur", "Dhule", "Gadchiroli", "Gondia", "Hingoli",
            "Jalgaon", "Jalna", "Kolhapur", "Latur", "Mumbai City", "Mumbai Suburban", "Nagpur",
            "Nanded", "Nandurbar", "Nashik", "Dharashiv (Osmanabad)", "Palghar", "Parbhani",
            "Pune", "Raigad (Panvel / Alibag)", "Ratnagiri", "Sangli", "Satara", "Sindhudurg",
            "Solapur", "Thane (Kalyan / Dombivli / Navi Mumbai)", "Wardha", "Washim", "Yavatmal",
            "Vasai-Virar", "Ichalkaranji", "Malegaon"
        ]
    },
    "Manipur": {
        "code": "MN",
        "stations": [
            "Bishnupur", "Chandel", "Churachandpur", "Imphal East", "Imphal West", "Jiribam",
            "Kakching", "Kamjong", "Kangpokpi", "Noney", "Pherzawl", "Senapati", "Tamenglong",
            "Tengnoupal", "Thoubal", "Ukhrul"
        ]
    },
    "Meghalaya": {
        "code": "ML",
        "stations": [
            "East Garo Hills (Williamnagar)", "East Jaintia Hills (Khliehriat)", "East Khasi Hills (Shillong)",
            "Eastern West Khasi Hills (Mairang)", "North Garo Hills (Resubelpara)", "Ri-Bhoi (Nongpoh)",
            "South Garo Hills (Baghmara)", "South West Garo Hills (Ampati)", "South West Khasi Hills (Mawkyrwat)",
            "West Garo Hills (Tura)", "West Jaintia Hills (Jowai)", "West Khasi Hills (Nongstoin)"
        ]
    },
    "Mizoram": {
        "code": "MZ",
        "stations": [
            "Aizawl", "Champhai", "Hnahthial", "Khawzawl", "Kolasib", "Lawngtlai",
            "Lunglei", "Mamit", "Saitual", "Serchhip", "Siaha"
        ]
    },
    "Nagaland": {
        "code": "NL",
        "stations": [
            "Chumoukedima", "Dimapur", "Kiphire", "Kohima", "Longleng", "Mokokchung", "Mon",
            "Niuland", "Noklak", "Peren", "Phek", "Shamator", "Tseminyu", "Tuensang", "Wokha", "Zunheboto"
        ]
    },
    "Odisha": {
        "code": "OD",
        "stations": [
            "Angul", "Balangir", "Balasore (Baleswar)", "Bargarh", "Bhadrak", "Boudh", "Cuttack",
            "Deogarh", "Dhenkanal", "Gajapati", "Ganjam (Berhampur)", "Jagatsinghpur (Paradip)",
            "Jajpur", "Jharsuguda", "Kalahandi (Bhawanipatna)", "Kandhamal (Phulbani)", "Kendrapara",
            "Kendujhar (Keonjhar)", "Khordha (Bhubaneswar)", "Koraput (Jeypore)", "Malkangiri",
            "Mayurbhanj (Baripada)", "Nabarangpur", "Nayagarh", "Nuapada", "Puri", "Rayagada",
            "Sambalpur", "Subarnapur (Sonepur)", "Sundargarh (Rourkela)"
        ]
    },
    "Punjab": {
        "code": "PB",
        "stations": [
            "Amritsar", "Barnala", "Bathinda", "Faridkot", "Fatehgarh Sahib", "Fazilka (Abohar)",
            "Firozpur", "Gurdaspur (Batala)", "Hoshiarpur", "Jalandhar", "Kapurthala (Phagwara)",
            "Ludhiana (Khanna)", "Malerkotla", "Mansa", "Moga", "Muktsar", "Pathankot",
            "Patiala (Rajpura)", "Rupnagar", "Sahibzada Ajit Singh Nagar (Mohali)", "Sangrur",
            "Shahid Bhagat Singh Nagar (Nawanshahr)", "Tarn Taran"
        ]
    },
    "Rajasthan": {
        "code": "RJ",
        "stations": [
            "Ajmer (Kishangarh / Beawar)", "Alwar (Bhiwadi)", "Anupgarh", "Balotra", "Banswara",
            "Baran", "Barmer", "Beawar", "Bharatpur", "Bhilwara", "Bikaner", "Bundi",
            "Chittorgarh", "Churu", "Dausa", "Deeg", "Dholpur", "Didwana-Kuchaman", "Dudu",
            "Dungarpur", "Gangapur City", "Hanumangarh", "Hindaun", "Jaipur", "Jaipur Rural",
            "Jaisalmer", "Jalore", "Jhalawar", "Jhunjhunu", "Jodhpur", "Jodhpur Rural",
            "Kekri", "Khairthal-Tijara", "Kota", "Kotputli-Behror", "Nagaur", "Neem Ka Thana",
            "Pali", "Phalodi", "Pratapgarh", "Rajsamand", "Salumbar", "Sanchore", "Sawai Madhopur",
            "Shahpura", "Sikar", "Sirohi", "Sri Ganganagar", "Tonk", "Udaipur"
        ]
    },
    "Sikkim": {
        "code": "SK",
        "stations": [
            "Gangtok", "Mangan", "Namchi", "Geyzing", "Pakyong", "Soreng", "Rangpo", "Singtam"
        ]
    },
    "Tamil Nadu": {
        "code": "TN",
        "stations": [
            "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore", "Dharmapuri",
            "Dindigul", "Erode", "Kallakurichi", "Kanchipuram", "Kanyakumari (Nagercoil)",
            "Karur", "Krishnagiri (Hosur)", "Madurai", "Mayiladuthurai", "Nagapattinam",
            "Namakkal", "Nilgiris (Udhagamandalam / Ooty)", "Perambalur", "Pudukkottai",
            "Ramanathapuram", "Ranipet", "Salem", "Sivaganga (Karaikudi)", "Tenkasi",
            "Thanjavur (Kumbakonam)", "Theni", "Thoothukudi (Tuticorin)", "Tiruchirappalli",
            "Tirunelveli", "Tirupathur", "Tiruppur", "Tiruvallur", "Tiruvannamalai", "Tiruvarur",
            "Vellore", "Viluppuram", "Virudhunagar (Sivakasi)"
        ]
    },
    "Telangana": {
        "code": "TS",
        "stations": [
            "Adilabad", "Bhadradri Kothagudem", "Hanumakonda", "Hyderabad", "Jagtial", "Jangaon",
            "Jayashankar Bhupalpally", "Jogulamba Gadwal", "Kamareddy", "Karimnagar", "Khammam",
            "Kumuram Bheem Asifabad", "Mahabubabad", "Mahbubnagar", "Mancherial", "Medak",
            "Medchal-Malkajgiri", "Mulugu", "Nagarkurnool", "Nalgonda", "Narayanpet", "Nirmal",
            "Nizamabad", "Peddapalli (Ramagundam)", "Rajanna Sircilla", "Ranga Reddy", "Sangareddy",
            "Siddipet", "Suryapet", "Vikarabad", "Wanaparthy", "Warangal", "Yadadri Bhuvanagiri"
        ]
    },
    "Tripura": {
        "code": "TR",
        "stations": [
            "Dhalai (Ambassa)", "Gomati (Udaipur)", "Khowai", "North Tripura (Dharmanagar)",
            "Sepahijala (Bishramganj)", "South Tripura (Belonia)", "Unakoti (Kailashahar)",
            "West Tripura (Agartala)"
        ]
    },
    "Uttar Pradesh": {
        "code": "UP",
        "stations": [
            "Agra", "Aligarh", "Ambedkar Nagar", "Amethi", "Amroha", "Auraiya", "Ayodhya",
            "Azamgarh", "Baghpat", "Bahraich", "Ballia", "Balrampur", "Banda", "Barabanki",
            "Bareilly", "Basti", "Bhadohi", "Bijnor", "Budaun", "Bulandshahr", "Chandauli",
            "Chitrakoot", "Deoria", "Etah", "Etawah", "Farrukhabad", "Fatehpur", "Firozabad",
            "Gautam Buddha Nagar (Noida / Greater Noida)", "Ghaziabad", "Ghazipur", "Gonda",
            "Gorakhpur", "Hamirpur", "Hapur", "Hardoi", "Hathras", "Jalaun (Orai)", "Jaunpur",
            "Jhansi", "Kannauj", "Kanpur Dehat", "Kanpur Nagar", "Kasganj", "Kaushambi",
            "Lakhimpur Kheri", "Kushinagar", "Lalitpur", "Lucknow", "Maharajganj", "Mahoba",
            "Mainpuri", "Mathura", "Mau", "Meerut", "Mirzapur", "Moradabad", "Muzaffarnagar",
            "Pilibhit", "Pratapgarh", "Prayagraj (Allahabad)", "Raebareli", "Rampur",
            "Saharanpur", "Sambhal", "Sant Kabir Nagar (Khalilabad)", "Shahjahanpur",
            "Shamli", "Shravasti", "Siddharthnagar", "Sitapur", "Sonbhadra", "Sultanpur",
            "Unnao", "Varanasi", "Modinagar"
        ]
    },
    "Uttarakhand": {
        "code": "UK",
        "stations": [
            "Almora", "Bageshwar", "Chamoli (Gopeshwar)", "Champawat", "Dehradun (Rishikesh)",
            "Haridwar (Roorkee)", "Nainital (Haldwani)", "Pauri Garhwal (Kotdwar)",
            "Pithoragarh", "Rudraprayag", "Tehri Garhwal (New Tehri)",
            "Udham Singh Nagar (Rudrapur / Kashipur / Pantnagar)", "Uttarkashi"
        ]
    },
    "West Bengal": {
        "code": "WB",
        "stations": [
            "Alipurduar", "Bankura", "Birbhum (Suri / Bolpur)", "Cooch Behar", "Dakshin Dinajpur (Balurghat)",
            "Darjeeling (Siliguri)", "Hooghly (Chinsurah / Chandannagar)", "Howrah", "Jalpaiguri",
            "Jhargram", "Kalimpong", "Kolkata", "Malda", "Murshidabad (Baharampur)",
            "Nadia (Krishnanagar / Kalyani)", "North 24 Parganas (Barasat / Bidhannagar)",
            "Paschim Bardhaman (Asansol / Durgapur)", "Paschim Medinipur (Midnapore / Kharagpur)",
            "Purba Bardhaman (Bardhaman)", "Purba Medinipur (Tamluk / Haldia)", "Purulia",
            "South 24 Parganas (Alipore)", "Uttar Dinajpur (Raiganj)"
        ]
    },
    "Andaman and Nicobar Islands": {
        "code": "AN",
        "stations": [
            "Port Blair", "South Andaman", "North and Middle Andaman (Mayabunder)",
            "Nicobar (Car Nicobar)", "Diglipur", "Rangat", "Hut Bay"
        ]
    },
    "Chandigarh": {
        "code": "CH",
        "stations": ["Chandigarh"]
    },
    "Dadra and Nagar Haveli and Daman and Diu": {
        "code": "DH",
        "stations": ["Daman", "Diu", "Dadra and Nagar Haveli (Silvassa)"]
    },
    "Delhi": {
        "code": "DL",
        "stations": [
            "New Delhi", "Central Delhi", "East Delhi", "North Delhi", "North East Delhi",
            "North West Delhi", "Shahdara", "South Delhi", "South East Delhi", "South West Delhi",
            "West Delhi", "Connaught Place", "Dwarka", "Rohini", "Karol Bagh", "Lajpat Nagar",
            "Chandni Chowk", "Okhla", "Laxmi Nagar", "Saket", "Hauz Khas", "Janakpuri",
            "Pitampura", "Vasant Kunj"
        ]
    },
    "Jammu and Kashmir": {
        "code": "JK",
        "stations": [
            "Anantnag", "Bandipora", "Baramulla", "Budgam", "Doda", "Ganderbal", "Jammu",
            "Kathua", "Kishtwar", "Kulgam", "Kupwara", "Poonch", "Pulwama", "Rajouri",
            "Ramban", "Reasi", "Samba", "Shopian", "Srinagar", "Udhampur", "Sopore"
        ]
    },
    "Ladakh": {
        "code": "LA",
        "stations": ["Leh", "Kargil", "Diskit", "Dras", "Nubra Valley"]
    },
    "Lakshadweep": {
        "code": "LD",
        "stations": ["Kavaratti", "Agatti", "Amini", "Andrott", "Minicoy", "Kalpeni", "Kadmat"]
    },
    "Puducherry": {
        "code": "PY",
        "stations": ["Puducherry", "Karaikal", "Mahe", "Yanam", "Ozhukarai"]
    }
}

# Clean and deduplicate stations per state
CLEANED_DATA = {}
for state, d in INDIA_DATA.items():
    seen = set()
    deduped = []
    for s in d["stations"]:
        name = s.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            deduped.append(name)
    deduped.sort()
    CLEANED_DATA[state] = {
        "code": d["code"],
        "stations": deduped
    }

def generate_typescript():
    """Generate frontend/src/features/goods-slips/indiaData.ts"""
    lines = [
        "// Auto-generated All India States & Stations (districts/cities) dataset for RMS Gate Entry.",
        "import type { LookupItem } from './api';",
        "",
        "export interface IndiaStateInfo {",
        "  code: string;",
        "  stations: string[];",
        "}",
        "",
        "export const INDIA_STATES_DATA: Record<string, IndiaStateInfo> = " + json.dumps(CLEANED_DATA, indent=2) + ";",
        "",
        "export const ALL_INDIA_STATES: LookupItem[] = Object.entries(INDIA_STATES_DATA)",
        "  .map(([name, info]) => ({",
        "    id: name,",
        "    name,",
        "    code: info.code,",
        "  }))",
        "  .sort((a, b) => a.name.localeCompare(b.name));",
        "",
        "/** Helper to get stations for a given state (by ID, Name, or Code) */",
        "export function getStationsForState(stateKey: string | null | undefined): LookupItem[] {",
        "  if (!stateKey) return [];",
        "  // 1. Exact name match",
        "  let info = INDIA_STATES_DATA[stateKey];",
        "  // 2. Case-insensitive or code match",
        "  if (!info) {",
        "    const normalized = stateKey.trim().toLowerCase();",
        "    for (const [name, s] of Object.entries(INDIA_STATES_DATA)) {",
        "      if (name.toLowerCase() === normalized || s.code.toLowerCase() === normalized) {",
        "        info = s;",
        "        break;",
        "      }",
        "    }",
        "  }",
        "  if (!info) return [];",
        "  return info.stations.map((stationName) => ({",
        "    id: stationName,",
        "    name: stationName,",
        "  })).sort((a, b) => a.name.localeCompare(b.name));",
        "}",
        ""
    ]
    path = Path("frontend/src/features/goods-slips/indiaData.ts")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {path}")

def generate_sql_migration():
    """Generate supabase/migrations/20261110000000_all_india_states_and_stations.sql"""
    lines = [
        "-- All India States and Stations (Districts/Cities) Migration",
        "-- Covers all 28 States and 8 Union Territories and their respective administrative districts/cities.",
        "",
        "-- 1. Populate all 36 States & UTs",
        "insert into public.states (code, name)",
        "values"
    ]
    state_values = []
    for name, data in sorted(CLEANED_DATA.items()):
        code = data["code"]
        name_esc = name.replace("'", "''")
        state_values.append(f"  ('{code}', '{name_esc}')")
    lines.append(",\n".join(state_values))
    lines.append("on conflict (name) do update set code = excluded.code, is_active = true;")
    lines.append("")
    lines.append("-- 2. Populate respective Stations (Districts/Cities)")
    lines.append("insert into public.stations (state_id, name)")
    lines.append("select s.id, v.station")
    lines.append("from (values")
    station_values = []
    for name, data in sorted(CLEANED_DATA.items()):
        name_esc = name.replace("'", "''")
        for station in data["stations"]:
            st_esc = station.replace("'", "''")
            station_values.append(f"  ('{name_esc}', '{st_esc}')")
    lines.append(",\n".join(station_values))
    lines.append(") as v(state_name, station)")
    lines.append("join public.states s on s.name = v.state_name")
    lines.append("on conflict (state_id, name) do nothing;")
    lines.append("")
    
    path = Path("supabase/migrations/20261110000000_all_india_states_and_stations.sql")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {path}")

if __name__ == "__main__":
    generate_typescript()
    generate_sql_migration()
