"""
VaaniPay — Audio Prompt Downloader
===================================
Downloads all IVR audio prompts from Sarvam AI TTS and saves them to prompt_audio/.

File naming: prompt_audio/{lang}_{prompt_key}.wav
Example:     prompt_audio/hi_main_menu.wav
             prompt_audio/en_enter_phone.wav

Usage:
    python download_audios.py              # generate all missing files
    python download_audios.py --force      # regenerate everything (overwrite)
    python download_audios.py --lang hi    # only generate Hindi prompts
    python download_audios.py --list       # print all prompt keys without downloading
    python download_audios.py --universal  # regenerate only the universal language menu

Set SARVAM_API_KEY in .env before running.
"""

import sys
import argparse
from pathlib import Path
from services.sarvam_tts import save_tts

PROMPT_DIR = Path(__file__).parent / "prompt_audio"

# =============================================================================
# PART 1 — UNIVERSAL LANGUAGE MENU (ONE file played to everyone on call start)
# Each line is in its own language so the caller recognises their language.
# Generated as: prompt_audio/universal_language_menu.wav  (English TTS)
# =============================================================================

UNIVERSAL_LANGUAGE_MENU = (
    "Welcome to VaaniPay. Your voice-first financial assistant. "
    "Hindi ke liye, ek dabayein. "
    "For English, press two. "
    "Tamil ku, moondru anukku. "
    "Telugu lo, naalu nakkandi. "
    "Kannada ge, aidu ottiri. "
    "Malayalam inu, aaru amarthuka. "
    "Marathi sathi, saat daba. "
    "Bangla ke liye, aath chapa diye. "
    "Gujarati mate, nav dabavo."
)

# =============================================================================
# PART 2 & 3 — SERVICE PROMPTS (IVR-friendly: spelled-out numbers,
#              expanded abbreviations, option 8 chatbot in main_menu)
# =============================================================================

SERVICE_PROMPTS = {
    "hi": {
        # Auth
        "enter_phone":      "Kripaya apna das ankon ka mobile number darj karein.",
        "enter_mpin":       "Kripaya apna chaar ankon ka m PIN darj karein.",
        "wrong_mpin":       "Galat m PIN. Kripaya punah prayas karein.",
        "mpin_locked":      "Bahut adhik galat prayas. Call samapt ho rahi hai.",
        "no_account":       "Is number par koi khata nahin mila. Dhanyavaad.",
        "auth_success":     "Praamanikaran safal. VaaniPay mein aapka swagat hai.",
        # Main menu — IVR friendly, spelt-out numbers, option eight added
        "main_menu": (
            "Mukhya menu. "
            "U P I bhugtaan ke liye ek dabayein. "
            "Balance dekhne ke liye do dabayein. "
            "Loan ke liye teen dabayein. "
            "Bima ke liye chaar dabayein. "
            "Credit score ke liye paanch dabayein. "
            "Bachat ke liye chhe dabayein. "
            "P F ya N P S balance ke liye saat dabayein. "
            "Vittiya sawaal poochne ke liye aath dabayein."
        ),
        # UPI
        "upi_ask_recipient": "Kripaya praaptakarta ka das ankon ka mobile number darj karein.",
        "upi_ask_amount":    "Kripaya rakam darj karein, phir hash dabayein.",
        "upi_confirm":       "Bhugtaan ki pushti karne ke liye ek dabayein, radad karne ke liye do.",
        "upi_success":       "Bhugtaan safal raha.",
        "upi_failed":        "Bhugtaan vifal. Kripaya punah prayas karein.",
        "upi_not_found":     "Praaptakarta ka khata nahin mila.",
        # Loan
        "loan_not_eligible": "Khed hai. Aapka credit score kam hai. Aap loan ke liye patra nahin hain.",
        "loan_ask_amount":   "Kripaya loan ki rakam darj karein, phir hash dabayein.",
        "loan_confirm":      "Loan ki pushti ke liye ek dabayein, radad ke liye do.",
        "loan_approved":     "Loan swikrit. Rakam aapke khate mein jama kar di jayegi.",
        "loan_rejected":     "Aapki patrta ke aadhar par loan aswikrit.",
        # Insurance
        "insurance_menu":    "Bima prakar chunein. Swasthya bima ke liye ek. Durghatna bima ke liye do. Fasal bima ke liye teen.",
        "insurance_confirm": "Bima sakt karne ke liye ek dabayein, radad ke liye do.",
        "insurance_success": "Bima safaltapurvak sakt.",
        # Savings
        "savings_menu":      "Bachat vikalp. Sthir jama ke liye ek. Aavarti jama ke liye do.",
        "savings_ask_amount": "Kripaya jama rakam darj karein, phir hash dabayein.",
        "savings_ask_duration": "Avadhi mahinon mein darj karein, phir hash dabayein.",
        "savings_confirm":    "Jama ki pushti ke liye ek dabayein.",
        "savings_success":    "Jama safaltapurvak darj.",
        # General
        "invalid":           "Amanya input. Kripaya punah prayas karein.",
        "goodbye":           "VaaniPay ka upyog karne ke liye dhanyavaad. Namaste.",
        "error":             "Tantrik samasya. Kripaya baad mein prayas karein.",
        "please_wait":       "Kripaya prateeksha karein.",
    },

    "en": {
        "enter_phone":      "Please enter your ten digit mobile number.",
        "enter_mpin":       "Please enter your four digit m PIN.",
        "wrong_mpin":       "Incorrect m PIN. Please try again.",
        "mpin_locked":      "Too many failed attempts. Ending call.",
        "no_account":       "No account found for this number. Thank you.",
        "auth_success":     "Authentication successful. Welcome to VaaniPay.",
        "main_menu": (
            "Main menu. "
            "For U P I payment, press one. "
            "For balance, press two. "
            "For loan, press three. "
            "For insurance, press four. "
            "For credit score, press five. "
            "For savings, press six. "
            "For P F or N P S balance, press seven. "
            "To ask financial questions, press eight."
        ),
        "upi_ask_recipient": "Please enter the recipient's ten digit mobile number.",
        "upi_ask_amount":    "Please enter the amount, then press hash.",
        "upi_confirm":       "Press one to confirm payment, press two to cancel.",
        "upi_success":       "Payment successful.",
        "upi_failed":        "Payment failed. Please try again.",
        "upi_not_found":     "Recipient account not found.",
        "loan_not_eligible": "Sorry, your credit score is too low. You are not eligible for a loan.",
        "loan_ask_amount":   "Please enter the loan amount, then press hash.",
        "loan_confirm":      "Press one to confirm loan, press two to cancel.",
        "loan_approved":     "Loan approved. Amount will be credited to your account.",
        "loan_rejected":     "Loan rejected based on your eligibility.",
        "insurance_menu":    "Choose insurance type. Press one for health insurance. Press two for accident insurance. Press three for crop insurance.",
        "insurance_confirm": "Press one to activate insurance, press two to cancel.",
        "insurance_success": "Insurance activated successfully.",
        "savings_menu":      "Savings options. Press one for Fixed Deposit. Press two for Recurring Deposit.",
        "savings_ask_amount": "Please enter the deposit amount, then press hash.",
        "savings_ask_duration": "Enter duration in months, then press hash.",
        "savings_confirm":    "Press one to confirm deposit.",
        "savings_success":    "Deposit recorded successfully.",
        "invalid":           "Invalid input. Please try again.",
        "goodbye":           "Thank you for using VaaniPay. Goodbye.",
        "error":             "Technical error. Please try again later.",
        "please_wait":       "Please wait.",
    },

    "ta": {
        "enter_phone":      "Ungal pathu ilakkam mobile enai ullidavum.",
        "enter_mpin":       "Ungal naangu ilakkam m PIN ullidavum.",
        "wrong_mpin":       "Thappaana m PIN. Meendum muyandrukavum.",
        "mpin_locked":      "Adhiga tholvigal. Azhaippu niruththappadukiradhu.",
        "no_account":       "Intha numberi kanakku illai.",
        "auth_success":     "Saandru unarpagam vetrrikaramaanavadhu. VaaniPay-il varavERppu.",
        "main_menu": (
            "Mookkiya menu. "
            "U P I seluththalukku ondru anukku. "
            "Nilai-ukku irandu anukku. "
            "Kadanukku moondru anukku. "
            "Kaappukku naangu anukku. "
            "Credit score-ukku aindhu anukku. "
            "Semipukku aaru anukku. "
            "P F alladu N P S-ukku eezhu anukku. "
            "Vittiya kelvi ketkka ettu anukku."
        ),
        "upi_ask_recipient": "Petralaar pathu ilakkam enai ullidavum.",
        "upi_ask_amount":    "Thokai ullidunga, hash anukku.",
        "upi_confirm":       "Seluththal uruthi ondru, raddu irandu.",
        "upi_success":       "Seluththal vetrrikaramaanavadhu.",
        "upi_failed":        "Seluththal tholviyuriyadhu.",
        "upi_not_found":     "Petralaar kanakku illai.",
        "loan_not_eligible": "Manikavum, neengal kadanukku thagudhi illai.",
        "loan_ask_amount":   "Kadan thokai ullidunga, hash anukku.",
        "loan_confirm":      "Kadan uruthi ondru, raddu irandu.",
        "loan_approved":     "Kadan anumathikkappattathu.",
        "loan_rejected":     "Kadan nirakkarikkappattathu.",
        "insurance_menu":    "Kaappu vagaippai thervusei. Ondru udalnaalam, irandu viduppattu, moondru payan.",
        "insurance_confirm": "Kaappu seyal ondru, raddu irandu.",
        "insurance_success": "Kaappu seyyappattathu.",
        "savings_menu":      "Semipu. Ondru niraiya vaipu, irandu thozharvu vaipu.",
        "savings_ask_amount": "Vaipu thokai ullidunga, hash anukku.",
        "savings_ask_duration": "Maadangalil kaalam ullidunga, hash anukku.",
        "savings_confirm":    "Uruthi ondru.",
        "savings_success":    "Vaipu pathivu seyyappattathu.",
        "invalid":           "Thappaana ullidai.",
        "goodbye":           "VaaniPay payanpaduttiyatharku nandri.",
        "error":             "Thazhnilai pazhuthu.",
        "please_wait":       "Thayavuseitu kaattirunga.",
    },

    "te": {
        "enter_phone":      "Meeru padi ankela mobile number namoodu cheyandi.",
        "enter_mpin":       "Meeru naalugu ankela m PIN namoodu cheyandi.",
        "wrong_mpin":       "Thappu m PIN. Meeru malli prayancinandi.",
        "mpin_locked":      "Ekkuva viphala prayanalu. Call muginipotundi.",
        "no_account":       "Ee numberu lo khaata ledu.",
        "auth_success":     "Dharuveekarana vijayavantamindi. VaaniPay ki swaagatam.",
        "main_menu": (
            "Pradhana menu. "
            "U P I chellimpu kosam okati nakkandi. "
            "Balance kosam rendu nakkandi. "
            "Runam kosam moodu nakkandi. "
            "Bheema kosam naalu nakkandi. "
            "Credit score kosam aidu nakkandi. "
            "Podupulu kosam aaru nakkandi. "
            "P F ledu N P S kosam edu nakkandi. "
            "Vittiya prasnalu aduguta enimidi nakkandi."
        ),
        "upi_ask_recipient": "Graheeta padi ankela number namoodu cheyandi.",
        "upi_ask_amount":    "Mottam namoodu chesi hash nakkandi.",
        "upi_confirm":       "Nirdharinchate okati, raddu rendu.",
        "upi_success":       "Chellimpu vijayavantamindi.",
        "upi_failed":        "Chellimpu viphalamaindi.",
        "upi_not_found":     "Graheeta khaata kanugonabadaledu.",
        "loan_not_eligible": "Ksaminchandi, meeru runaniki arhulu kaadu.",
        "loan_ask_amount":   "Runam mottam namoodu chesi hash nakkandi.",
        "loan_confirm":      "Runam nirdharana okati, raddu rendu.",
        "loan_approved":     "Runam manjuruaindi.",
        "loan_rejected":     "Runam thiraskarinchababaindi.",
        "insurance_menu":    "Bheema rakaamu. Okati Aarogyam, rendu Pramaadam, moodu Pandlu.",
        "insurance_confirm": "Bheema sakriyam okati, raddu rendu.",
        "insurance_success": "Bheema sakriyamindi.",
        "savings_menu":      "Podupulu. Okati Sthira Deposit, rendu Punareeksha Deposit.",
        "savings_ask_amount": "Mottam namoodu chesi hash nakkandi.",
        "savings_ask_duration": "Nelallo kaalaavadhi namoodu chesi hash nakkandi.",
        "savings_confirm":    "Nirdharinchate okati.",
        "savings_success":    "Deposit nondaindi.",
        "invalid":           "Chaellani input.",
        "goodbye":           "VaaniPay upayoginchinduku dhanyavaadaalu.",
        "error":             "Sangeetika paatha.",
        "please_wait":       "Dayachesi veechinchandi.",
    },

    "kn": {
        "enter_phone":      "Nimma hattu ankiya mobile sankhye namoodisi.",
        "enter_mpin":       "Nimma naalku ankiya m PIN namoodisi.",
        "wrong_mpin":       "Tappu m PIN. Matte prayathnisi.",
        "mpin_locked":      "Hechu tappu prayathnagalu. Kare mugiyuttide.",
        "no_account":       "Ee sankhyege khate illa.",
        "auth_success":     "Pramaanikarana yashashvi. VaaniPay ge swagata.",
        "main_menu": (
            "Mukhya menu. "
            "U P I pavathi ge ondu ottiri. "
            "Shalku ge eradu ottiri. "
            "Sala ge mooru ottiri. "
            "Vime ge naalku ottiri. "
            "Credit score ge aidu ottiri. "
            "Ulitaaya ge aaru ottiri. "
            "P F athava N P S ge elu ottiri. "
            "Vittiya prashnegalaadaalu enta ottiri."
        ),
        "upi_ask_recipient": "Sveekarisi taakiya hattu ankiya sankhye namoodisi.",
        "upi_ask_amount":    "Motta namoodisi, hash ottiri.",
        "upi_confirm":       "Dhrudheekarisalu ondu, raddu eradu.",
        "upi_success":       "Pavathi yashashvi.",
        "upi_failed":        "Pavathi viphala.",
        "upi_not_found":     "Sveekarisi taakaravara khate illa.",
        "loan_not_eligible": "Kshamisi, neevu salanukke arhavagilla.",
        "loan_ask_amount":   "Sala motta namoodisi, hash ottiri.",
        "loan_confirm":      "Sala dhrudheekarana ondu, raddu eradu.",
        "loan_approved":     "Sala anumodita.",
        "loan_rejected":     "Sala nirasita.",
        "insurance_menu":    "Vime prakaara. Ondu Aarogyam, eradu Apaghaata, mooru Beralu.",
        "insurance_confirm": "Vime sakraya ondu, raddu eradu.",
        "insurance_success": "Vime sakrayagide.",
        "savings_menu":      "Ulitaaya. Ondu Sthira Vandana, eradu Aavrtti Vandana.",
        "savings_ask_amount": "Motta namoodisi, hash ottiri.",
        "savings_ask_duration": "Tingaligalalli avadhi namoodisi, hash ottiri.",
        "savings_confirm":    "Dhrudheekarisalu ondu.",
        "savings_success":    "Vandana daakhala.",
        "invalid":           "Amanya input.",
        "goodbye":           "VaaniPay balasi dhannavada.",
        "error":             "Tantrika doorti.",
        "please_wait":       "Dayavittu neeredisi.",
    },

    "ml": {
        "enter_phone":      "Ninnude pathu akkamulla mobile number nalkuka.",
        "enter_mpin":       "Ninnude naalu akkamulla m PIN nalkuka.",
        "wrong_mpin":       "Theettaya m PIN. Vendum shreemikuka.",
        "mpin_locked":      "Eera parichodhanagal adhikamaayi. Kol avasaanikkunnu.",
        "no_account":       "Ee numberin account kaanikkunilla.",
        "auth_success":     "Pramaanikaranam vijayakaram. VaaniPay-il swaagatam.",
        "main_menu": (
            "Pradhana menu. "
            "U P I payment-inu onnu amarthuka. "
            "Balance-inu randu amarthuka. "
            "Loan-inu moonu amarthuka. "
            "Insurance-inu naalu amarthuka. "
            "Credit score-inu anchu amarthuka. "
            "Savings-inu aaru amarthuka. "
            "P F allenkil N P S-inu ezhu amarthuka. "
            "Vittiya chodyangalkku ettu amarthuka."
        ),
        "upi_ask_recipient": "Sveekartavante pathu akkamulla number nalkuka.",
        "upi_ask_amount":    "Thukaanu nalkuka, pin hash arakkuka.",
        "upi_confirm":       "Sthirikarikkan onnu, raddu randu.",
        "upi_success":       "Payment vijayakaram.",
        "upi_failed":        "Payment parajayapettu.",
        "upi_not_found":     "Sveekartavante account kaanikunilla.",
        "loan_not_eligible": "Kshamikkanam, neenga loan-inu yogyaralla.",
        "loan_ask_amount":   "Loan thukaanu nalkuka, hash arakkuka.",
        "loan_confirm":      "Loan sthireekaranam onnu, raddu randu.",
        "loan_approved":     "Loan anumathicha.",
        "loan_rejected":     "Loan nirasichchi.",
        "insurance_menu":    "Insurance tharam. Onnu Aarogyam, randu Aapaddhu, moonu Velam.",
        "insurance_confirm": "Insurance pravarthanam onnu, raddu randu.",
        "insurance_success": "Insurance pravarthanam vijayakaram.",
        "savings_menu":      "Savings. Onnu Fixed Deposit, randu Recurring Deposit.",
        "savings_ask_amount": "Thukaanu nalkuka, hash arakkuka.",
        "savings_ask_duration": "Maasangalil kaalavadhi nalkuka, hash arakkuka.",
        "savings_confirm":    "Sthireekarikkan onnu.",
        "savings_success":    "Deposit rekha.",
        "invalid":           "Asaadhu input.",
        "goodbye":           "VaaniPay upayogichathin nandhi.",
        "error":             "Samperka pathivu.",
        "please_wait":       "Dayavaayi kaathu nilkkuka.",
    },

    "mr": {
        "enter_phone":      "Krupaya tumcha das anki mobile number pravesh kara.",
        "enter_mpin":       "Krupaya tumcha chaar anki m PIN pravesh kara.",
        "wrong_mpin":       "Chukicha m PIN. Punha prayas kara.",
        "mpin_locked":      "Jast chukiche prayas. Call sampat ahe.",
        "no_account":       "Ya numbervara khate aadhal naahi.",
        "auth_success":     "Pramineekarana yashashvi. VaaniPay madhye svagat.",
        "main_menu": (
            "Mukhya menu. "
            "U P I deykasathi ek daba. "
            "Shilakaasathi don daba. "
            "Karja sathi teen daba. "
            "Vimyasathi chaar daba. "
            "Credit score sathi paach daba. "
            "Bachatsathi saha daba. "
            "P F kinva N P S sathi saat daba. "
            "Vittiya prashn vicharanyasathi aath daba."
        ),
        "upi_ask_recipient": "Praptakartyacha das anki number pravesh kara.",
        "upi_ask_amount":    "Rakam pravesh kara, mag hash daba.",
        "upi_confirm":       "Deyk pustikarat ek, radda don.",
        "upi_success":       "Deyk yashashvi.",
        "upi_failed":        "Deyk apayashi.",
        "upi_not_found":     "Praptakartyache khate sapadal naahi.",
        "loan_not_eligible": "Maaf kara, tum karja sathi patra naahit.",
        "loan_ask_amount":   "Karja rakam pravesh kara, hash daba.",
        "loan_confirm":      "Karja pustikaran ek, radda don.",
        "loan_approved":     "Karja manjur.",
        "loan_rejected":     "Karja nakar.",
        "insurance_menu":    "Vima prakar. Ek Aarogya, don Apghaat, teen Peek.",
        "insurance_confirm": "Vima sakriya ek, radda don.",
        "insurance_success": "Vima yashashviri ta sakriya.",
        "savings_menu":      "Bachat vikalp. Ek Mudat thev, don Aavrti thev.",
        "savings_ask_amount": "Rakam pravesh kara, hash daba.",
        "savings_ask_duration": "Mahinyanmadhe avadhi pravesh kara, hash daba.",
        "savings_confirm":    "Pustikaran sathi ek.",
        "savings_success":    "Thev nondvali.",
        "invalid":           "Ayogya input.",
        "goodbye":           "VaaniPay vaparlyas abhar.",
        "error":             "Tantrik samasya.",
        "please_wait":       "Krupaya pratiksha kara.",
    },

    "bn": {
        "enter_phone":      "Apnar dosh sankhyar mobile number diun.",
        "enter_mpin":       "Apnar char sankhyar m PIN diun.",
        "wrong_mpin":       "Bhul m PIN. Abar cheshta korun.",
        "mpin_locked":      "Onek bhul cheshta. Call shesh hochche.",
        "no_account":       "Ei numbere kono account paoa jaaini.",
        "auth_success":     "Pramanikaran safal. VaaniPay-e swagato.",
        "main_menu": (
            "Mukhya menu. "
            "U P I payment-er jonyo ek chapa diye. "
            "Balance-er jonyo dui chapa diye. "
            "Rin-er jonyo tin chapa diye. "
            "Bima-r jonyo char chapa diye. "
            "Credit score-er jonyo panch chapa diye. "
            "Shanchoy-er jonyo chhoy chapa diye. "
            "P F ba N P S-er jonyo saat chapa diye. "
            "Vittiya proshno korar jonyo aath chapa diye."
        ),
        "upi_ask_recipient": "Grahakero dosh sankhyar number diun.",
        "upi_ask_amount":    "Parimaan diun, tokhon hash chapa diye.",
        "upi_confirm":       "Payment nishchit ek, raddo dui.",
        "upi_success":       "Payment safal.",
        "upi_failed":        "Payment biphal.",
        "upi_not_found":     "Grahakero account paoa jaaini.",
        "loan_not_eligible": "Dukkhit, aapni rin paaoar janya jogyo na.",
        "loan_ask_amount":   "Rin parimaan diun, hash chapa diye.",
        "loan_confirm":      "Rin nishchintokaari ek, raddo dui.",
        "loan_approved":     "Rin anumodit.",
        "loan_rejected":     "Rin prakhya anit.",
        "insurance_menu":    "Bima prakar. Ek Swasthya, dui Durghothna, tin Fasal.",
        "insurance_confirm": "Bima saktiya ek, raddo dui.",
        "insurance_success": "Bima safalbhabe saktiya.",
        "savings_menu":      "Shanchoy. Ek Sthira Amaanat, dui Punoravritti Amaanat.",
        "savings_ask_amount": "Parimaan diun, hash chapa diye.",
        "savings_ask_duration": "Maasey kaaalkaal diun, hash chapa diye.",
        "savings_confirm":    "Nishchit ek.",
        "savings_success":    "Amaanat nathivukt.",
        "invalid":           "Baidho input.",
        "goodbye":           "VaaniPay baybaharer jonyo dhanyabaad.",
        "error":             "Tantrik samasya.",
        "please_wait":       "Doyakore apekkhaa korun.",
    },

    "gu": {
        "enter_phone":      "Krupa karine tamaro das anko no mobile number darj karo.",
        "enter_mpin":       "Krupa karine tamaro chaar anko no m PIN darj karo.",
        "wrong_mpin":       "Khoṭo m PIN. Pharthi prayas karo.",
        "mpin_locked":      "Ghano khoṭa prayaso. Kol paṭo thaay che.",
        "no_account":       "Aa number par khatu malyu nathi.",
        "auth_success":     "Pramanikaran saphal. VaaniPay ma aapnu swagat che.",
        "main_menu": (
            "Mukhy menu. "
            "U P I chukvani mate ek dabavo. "
            "Balance mate be dabavo. "
            "Loan mate tran dabavo. "
            "Vima mate chaar dabavo. "
            "Credit score mate paanch dabavo. "
            "Bachat mate chha dabavo. "
            "P F athava N P S mate saat dabavo. "
            "Vittiya prashno poochhva aath dabavo."
        ),
        "upi_ask_recipient": "Melo sautano das anko no number darj karo.",
        "upi_ask_amount":    "Rakam darj karo, pachhi hash dabavo.",
        "upi_confirm":       "Chukvani ni pushti ek, raddo be.",
        "upi_success":       "Chukvani saphal.",
        "upi_failed":        "Chukvani niphal.",
        "upi_not_found":     "Melo sutano khatu malyu nathi.",
        "loan_not_eligible": "Maaf karo, tame loan mate layak nathi.",
        "loan_ask_amount":   "Loan ni rakam darj karo, hash dabavo.",
        "loan_confirm":      "Loan ni pushti ek, raddo be.",
        "loan_approved":     "Loan manjur.",
        "loan_rejected":     "Loan nakaru.",
        "insurance_menu":    "Vima prakar. Ek Swasthya, be Aapatti, tran Pako.",
        "insurance_confirm": "Vima sakriya ek, raddo be.",
        "insurance_success": "Vima saphal rite sakriya.",
        "savings_menu":      "Bachat vikalpo. Ek Sthir Thapan, be Punaravrti Thapan.",
        "savings_ask_amount": "Rakam darj karo, hash dabavo.",
        "savings_ask_duration": "Mahinaama gaalo darj karo, hash dabavo.",
        "savings_confirm":    "Pushti mate ek.",
        "savings_success":    "Thapan nondhayu.",
        "invalid":           "Amanya input.",
        "goodbye":           "VaaniPay vaapravaa badal aabhar.",
        "error":             "Tantrik samasya.",
        "please_wait":       "Krupa karine raho.",
    },
}


# =============================================================================
# DOWNLOAD LOGIC
# =============================================================================

def download_universal_menu(force: bool = False) -> tuple[int, int]:
    """Generate the single universal language menu file."""
    out_path = PROMPT_DIR / "universal_language_menu.wav"
    print("\n=== Universal Language Menu ===")
    if out_path.exists() and not force:
        print(f"  SKIP (exists): {out_path.name}")
        return 1, 0
    print(f"  Generating: {out_path.name} ...", end=" ", flush=True)
    # Use English TTS — the text is a mix of transliterations readable by English TTS
    if save_tts(UNIVERSAL_LANGUAGE_MENU, "en", out_path):
        print("OK")
        return 1, 0
    print("FAIL")
    return 0, 1


def download_service_prompts(force: bool = False, lang_filter: str | None = None) -> tuple[int, int]:
    """Download all per-language service prompts."""
    ok = 0
    fail = 0
    langs = [lang_filter] if lang_filter else list(SERVICE_PROMPTS.keys())

    for lang_key in langs:
        prompts = SERVICE_PROMPTS.get(lang_key)
        if not prompts:
            print(f"\n  WARNING: no prompts defined for lang '{lang_key}'")
            continue

        print(f"\n=== [{lang_key}] Service Prompts ===")
        for prompt_key, text in prompts.items():
            out_path = PROMPT_DIR / f"{lang_key}_{prompt_key}.wav"
            if out_path.exists() and not force:
                print(f"  SKIP (exists): {out_path.name}")
                ok += 1
                continue
            print(f"  Generating: {out_path.name} ...", end=" ", flush=True)
            if save_tts(text, lang_key, out_path):
                print("OK")
                ok += 1
            else:
                print("FAIL")
                fail += 1

    return ok, fail


def main():
    parser = argparse.ArgumentParser(description="Download VaaniPay IVR audio prompts via Sarvam AI TTS")
    parser.add_argument("--force",     action="store_true", help="Regenerate even if file already exists")
    parser.add_argument("--lang",      type=str, default=None, help="Only generate for one language (e.g. --lang hi)")
    parser.add_argument("--list",      action="store_true", help="Print all prompt keys without downloading")
    parser.add_argument("--universal", action="store_true", help="Regenerate only the universal language menu")
    args = parser.parse_args()

    if args.list:
        print("\nUniversal menu:")
        print("  prompt_audio/universal_language_menu.wav")
        print("\nService prompts:")
        for lang_key, prompts in SERVICE_PROMPTS.items():
            for key in prompts:
                print(f"  prompt_audio/{lang_key}_{key}.wav")
        total = 1 + sum(len(v) for v in SERVICE_PROMPTS.values())
        print(f"\nTotal: {total} files")
        return

    PROMPT_DIR.mkdir(exist_ok=True)
    total_ok = 0
    total_fail = 0

    if args.universal:
        ok, fail = download_universal_menu(force=True)
        total_ok += ok
        total_fail += fail
    elif not args.lang:
        ok, fail = download_universal_menu(force=args.force)
        total_ok += ok
        total_fail += fail

    ok, fail = download_service_prompts(force=args.force, lang_filter=args.lang)
    total_ok += ok
    total_fail += fail

    print(f"\n{'='*50}")
    print(f"Done: {total_ok} succeeded, {total_fail} failed")
    if total_fail > 0:
        print("Re-run to retry failed files (skips already-downloaded ones automatically).")


if __name__ == "__main__":
    main()
