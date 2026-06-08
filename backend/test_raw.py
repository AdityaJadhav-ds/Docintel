import sys
sys.path.append('.')
from app.parsers.aadhaar_parser import parse_aadhaar
raw_text = """aor, C_ Government of India -"- Tare S |_| Aditya Bhagavan Jadhav
= as steat fa / DOB: 05/02/2004
= : qet/ Male
6340 9120 0603
SELMA OME Sa TORE a OR RNC ee ea RIM OS PR ADORED ETE one ART 3ITe In N FN) Gediet
C_ Government of India =-" _ Aditya Bhagavan Jadhav
sist AP / DOB: 05/02/2004
Ter / Male ANT 3c, ANY Ged STAs ANd tar wee wet Heer Aaa ST
aieat far / DOB: 05/02/2004
qet/ Male ANT 3a, ANT Uealet
< a ee ie Tae e B e S C Government of India >=" sirare ot SGee Haat STETA
S Aditya Bhagavan Jadhav
= ~s afew fafa / DOB: 05/02/2004
= asf) yeas Male
Se ee AQ 3e, ANT Gediet CT tite mane Weel Wade TIT Aditya Bhagavan Jadhav
aieat fafa / DOB: 05/02/2004
Ter / Male AQT Ze, ANT Weadiet FN Arar Sener a T Hecl Wale STI
a C Government of India = rare = ee \_ |Aditya Bhagavan Jadhav
= ISS) ! 2 aie ff / DOB: 05/02/2004
= Wd Ny a : : yer / Male
nn nnnnnneneeeen_d EE EEE TERREREEEEn R Gna ART 3x, ALT Weeder
ernment o Seo ea Aditya Bhagavan Jadhav
a aed fafa / DOB: 05/02/2004
Fea / Male STUa TS eer vod C Govemment of India TH fect aaaret ST
Aditya Bhagavan Jadhav
> ; sient fafa / DOB: 05/02/2004
Ter/ Male
Cate) Government of India "=" TET A Sea Haat STA S Aditya Bhagavan Jadhav
>. ae fart / DOB: 05/02/2004
a ) Tea / Male
ie LSB on ramen Hrare Macs HAa Talet ST Aditya Bhagavan Jadhav
aa fat / DOB: 05/02/2004
qeq / Male tt A FRA War a ee aeeeearieerae Heel Haale BT
aia fafa / DOB: 05/02/2004
AQT 3e I, ALY Gediet"""

res = parse_aadhaar(raw_text)
print("EXTRACTED NAME:", res["name"])
print("DEBUG CANDIDATES:", res.get("debug", {}))
