"""
SwaramPay — Audio Prompt Downloader
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
    "Welcome to SwaramPay. Your voice-first financial assistant. "
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
        "auth_success":     "Praamanikaran safal. SwaramPay mein aapka swagat hai.",
        "how_can_i_help":   "Namaste! Main aapki kaise madad kar sakta hoon?",
        # Conversational payment flow
        "who_to_pay":       "Kise paise bhejna hai? Naam ya unka number boliye.",
        "how_much":         "Kitne rupaye bhejna hai?",
        "not_understood":   "Maaf kijiye, mujhe samajh nahi aaya. Main filhaal sirf payment aur balance check mein madad kar sakta hoon.",
        "recipient_nf":     "Maaf kijiye, mujhe yeh contact nahi mila. Phir se koshish karein.",
        "amount_nu":        "Maaf kijiye, rashi samajh nahi aayi. Phir se koshish karein.",
        # MPIN setup (registration)
        "mpin_setup":       "Ab keypad se apna 4 ank ka secret PIN banayein. Yeh PIN aap baad mein login ke liye istemal karenge.",
        "mpin_confirm":     "Confirm karne ke liye, apna PIN dobara daalein.",
        "mpin_mismatch":    "PIN match nahi hua. Phir se shuru karte hain.",
        # Contacts
        "contact_name":     "Unka naam ya rishta boliye. Jaise bhatija, beti, ya dost.",
        "contact_number":   "Unka 10 ank ka number boliye.",
        "contact_dtmf":     "Keypad se unka 10 ank ka number daalen.",
        "contact_saved":    "Contact save ho gaya.",
        # Enrollment
        "enroll_retry":     "Awaaz record karne mein samasya aayi. Kripya phir se try karein.",
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
        "insufficient_balance": "Aapke khaate mein itni rashi uplabdh nahin hai.",
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
        "goodbye":           "SwaramPay ka upyog karne ke liye dhanyavaad. Namaste.",
        "error":             "Tantrik samasya. Kripaya baad mein prayas karein.",
        "please_wait":       "Kripaya prateeksha karein.",
    },

    "en": {
        "enter_phone":      "Please enter your ten digit mobile number.",
        "enter_mpin":       "Please enter your four digit m PIN.",
        "wrong_mpin":       "Incorrect m PIN. Please try again.",
        "mpin_locked":      "Too many failed attempts. Ending call.",
        "no_account":       "No account found for this number. Thank you.",
        "auth_success":     "Authentication successful. Welcome to SwaramPay.",
        "how_can_i_help":   "Hello! How can I help you?",
        "who_to_pay":       "Who would you like to send money to? Please say their name or number.",
        "how_much":         "How much money would you like to send?",
        "not_understood":   "Sorry, I didn't understand. I can currently help with payments and balance checks.",
        "recipient_nf":     "Sorry, I couldn't find that contact. Please try again.",
        "amount_nu":        "Sorry, I didn't catch the amount. Please try again.",
        "mpin_setup":       "Now set up a 4-digit secret PIN using your keypad. You'll use this PIN to log in later.",
        "mpin_confirm":     "To confirm, please enter the same PIN again.",
        "mpin_mismatch":    "The PINs didn't match. Let's set it up again.",
        "contact_name":     "Please say their name or relationship. For example: nephew, daughter, or friend.",
        "contact_number":   "Please say their 10-digit mobile number.",
        "contact_dtmf":     "Please enter their 10-digit number on the keypad.",
        "contact_saved":    "Contact saved successfully.",
        "enroll_retry":     "There was a problem recording your voice. Please try again.",
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
        "insufficient_balance": "You don't have enough balance for this payment.",
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
        "goodbye":           "Thank you for using SwaramPay. Goodbye.",
        "error":             "Technical error. Please try again later.",
        "please_wait":       "Please wait.",
    },

    "ta": {
        "enter_phone":      "Ungal pathu ilakkam mobile enai ullidavum.",
        "enter_mpin":       "Ungal naangu ilakkam m PIN ullidavum.",
        "wrong_mpin":       "Thappaana m PIN. Meendum muyandrukavum.",
        "mpin_locked":      "Adhiga tholvigal. Azhaippu niruththappadukiradhu.",
        "no_account":       "Intha numberi kanakku illai.",
        "auth_success":     "Saandru unarpagam vetrrikaramaanavadhu. SwaramPay-il varavERppu.",
        "how_can_i_help":   "Vanakkam! Naan ungalukku eppadi udhavi seyyalaam?",
        "who_to_pay":       "Yaarukku panam anuppanum? Peyar alladhu number sollunga.",
        "how_much":         "Evvalavu panam anuppanum?",
        "not_understood":   "Mannikavum, puriyavillai. Naan ippodhu payment matrum balance check ku mattum udhavi seiya mudiyum.",
        "recipient_nf":     "Mannikavum, antha contact kandupidikka mudiyala. Thirumba try pannunga.",
        "amount_nu":        "Mannikavum, thogai puriyavillai. Thirumba try pannunga.",
        "mpin_setup":       "Ippodhu keypad-il ungal 4 ilakka secret PIN-ai amaikkavum. Idhai pinnar login seiya payanpadutthuveergal.",
        "mpin_confirm":     "Confirm seiya, ungal PIN-ai meendum podunga.",
        "mpin_mismatch":    "PIN porunthavillai. Meendum try pannunga.",
        "contact_name":     "Avanga peyar ya uravu solunga. Udaharanam: marumagal, magal.",
        "contact_number":   "Avanga 10 ilakka number sollunga.",
        "contact_dtmf":     "Keypad il avanga number type pannunga.",
        "contact_saved":    "Contact save aanathu.",
        "enroll_retry":     "Kural record seiya mushkilaagiirundu. Meedum try pannunga.",
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
        "insufficient_balance": "Indha paymentirku poodhumana balance illai.",
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
        "goodbye":           "SwaramPay payanpaduttiyatharku nandri.",
        "error":             "Thazhnilai pazhuthu.",
        "please_wait":       "Thayavuseitu kaattirunga.",
    },

    "te": {
        "enter_phone":      "Meeru padi ankela mobile number namoodu cheyandi.",
        "enter_mpin":       "Meeru naalugu ankela m PIN namoodu cheyandi.",
        "wrong_mpin":       "Thappu m PIN. Meeru malli prayancinandi.",
        "mpin_locked":      "Ekkuva viphala prayanalu. Call muginipotundi.",
        "no_account":       "Ee numberu lo khaata ledu.",
        "auth_success":     "Dharuveekarana vijayavantamindi. SwaramPay ki swaagatam.",
        "how_can_i_help":   "Namaskaram! Nenu meeku ela sahayam cheyagalanu?",
        "who_to_pay":       "Evariki dabbu pampali? Vaari peru leda number cheppandi.",
        "how_much":         "Entha dabbu pampali?",
        "not_understood":   "Sorry, ardham kaaledu. Nenu ippudu payment mariyu balance check lo matrame sahayam cheyagalanu.",
        "recipient_nf":     "Sorry, aa contact kanugonaledu. Marala try cheyandi.",
        "amount_nu":        "Sorry, amount ardham kaaledu. Marala try cheyandi.",
        "mpin_setup":       "Ippudu keypad to mee 4 digits secret PIN set cheyandi. Idi taruvata login ki vadatharu.",
        "mpin_confirm":     "Confirm cheyataniki, mee PIN malli enter cheyandi.",
        "mpin_mismatch":    "PIN match avvaledu. Marala try cheyandi.",
        "contact_name":     "Vaari peru leda sambandham cheppandi. Udaharnamu: bhanjaa, kuthuru.",
        "contact_number":   "Vaari 10 digits number cheppandi.",
        "contact_dtmf":     "Keypad lo vaari number enter cheyyandi.",
        "contact_saved":    "Contact save ayyindi.",
        "enroll_retry":     "Voice record lo problem ayindi. Malli try cheyyandi.",
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
        "insufficient_balance": "Ee chellimpu kosam saripadina balance ledu.",
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
        "goodbye":           "SwaramPay upayoginchinduku dhanyavaadaalu.",
        "error":             "Sangeetika paatha.",
        "please_wait":       "Dayachesi veechinchandi.",
    },

    "kn": {
        "enter_phone":      "Nimma hattu ankiya mobile sankhye namoodisi.",
        "enter_mpin":       "Nimma naalku ankiya m PIN namoodisi.",
        "wrong_mpin":       "Tappu m PIN. Matte prayathnisi.",
        "mpin_locked":      "Hechu tappu prayathnagalu. Kare mugiyuttide.",
        "no_account":       "Ee sankhyege khate illa.",
        "auth_success":     "Pramaanikarana yashashvi. SwaramPay ge swagata.",
        "how_can_i_help":   "Namaskara! Naanu nimage hege sahaaya maadabahudu?",
        "who_to_pay":       "Yaarige hana kaludisbeku? Avara hesaru athava sankhye heli.",
        "how_much":         "Eshtu hana kaludisbeku?",
        "not_understood":   "Kshamisi, artha aagalilla. Naanu ividu payment mattu balance check nalli matra sahaaya maadabahudu.",
        "recipient_nf":     "Kshamisi, aa contact sigalilla. Marali try madi.",
        "amount_nu":        "Kshamisi, mottha artha aagalilla. Marali try madi.",
        "mpin_setup":       "Ivagu keypad nalli nimma 4 anki secret PIN set madi. Idannu mundina login ge baLasuviri.",
        "mpin_confirm":     "Khatarisalu, nimma PIN annu marali enter madi.",
        "mpin_mismatch":    "PIN match aagalilla. Marali prayatnisi.",
        "contact_name":     "Avara hesaru athava sambandha heli. Udaharana: bhanje, magalu.",
        "contact_number":   "Avara 10 ankidha sankhya heli.",
        "contact_dtmf":     "Keypad nali avara number enter madi.",
        "contact_saved":    "Contact save aayithu.",
        "enroll_retry":     "Voice record ge samasye. Dayavittu matte try madi.",
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
        "insufficient_balance": "Ee pavathige saakashtu balance illa.",
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
        "goodbye":           "SwaramPay balasi dhannavada.",
        "error":             "Tantrika doorti.",
        "please_wait":       "Dayavittu neeredisi.",
    },

    "ml": {
        "enter_phone":      "Ninnude pathu akkamulla mobile number nalkuka.",
        "enter_mpin":       "Ninnude naalu akkamulla m PIN nalkuka.",
        "wrong_mpin":       "Theettaya m PIN. Vendum shreemikuka.",
        "mpin_locked":      "Eera parichodhanagal adhikamaayi. Kol avasaanikkunnu.",
        "no_account":       "Ee numberin account kaanikkunilla.",
        "auth_success":     "Pramaanikaranam vijayakaram. SwaramPay-il swaagatam.",
        "how_can_i_help":   "Namaskaram! Njan ningale enthu sahayikkanam?",
        "who_to_pay":       "Aarkku panam ayakkanam? Avarude per allenkil number parayoo.",
        "how_much":         "Ethra panam ayakkanam?",
        "not_understood":   "Kshamikkanam, manasilaayilla. Ippol njan payment, balance check ennivayil mathram sahayikkam.",
        "recipient_nf":     "Kshamikkanam, aa contact kandilla. Veendum try cheyyu.",
        "amount_nu":        "Kshamikkanam, amount manasilaayilla. Veendum try cheyyu.",
        "mpin_setup":       "Ippol keypad upayogichu ningalude 4 digit secret PIN set cheyyu. Idu pinnit login cheyyan upayogikkum.",
        "mpin_confirm":     "Confirm cheyyan, PIN veendum enter cheyyu.",
        "mpin_mismatch":    "PIN match aayilla. Veendum cheyyu.",
        "contact_name":     "Avante peru athava bandham parayan. Udaharanam: bhatajar, magal.",
        "contact_number":   "Avante 10 digit number parayan.",
        "contact_dtmf":     "Keypad il avante number enter cheyyoo.",
        "contact_saved":    "Contact save cheythu.",
        "enroll_retry":     "Shwaram record cheyyaan problem. Onnu koodi try cheyyoo.",
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
        "insufficient_balance": "Ee paymentinu mathiyaya balance illa.",
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
        "goodbye":           "SwaramPay upayogichathin nandhi.",
        "error":             "Samperka pathivu.",
        "please_wait":       "Dayavaayi kaathu nilkkuka.",
    },

    "mr": {
        "enter_phone":      "Krupaya tumcha das anki mobile number pravesh kara.",
        "enter_mpin":       "Krupaya tumcha chaar anki m PIN pravesh kara.",
        "wrong_mpin":       "Chukicha m PIN. Punha prayas kara.",
        "mpin_locked":      "Jast chukiche prayas. Call sampat ahe.",
        "no_account":       "Ya numbervara khate aadhal naahi.",
        "auth_success":     "Pramineekarana yashashvi. SwaramPay madhye svagat.",
        "how_can_i_help":   "Namaskar! Mi tumchi kashi madat karu shakto?",
        "who_to_pay":       "Konala paise pathavayche? Tyanche naav kinva number sanga.",
        "how_much":         "Kiti paise pathavayche?",
        "not_understood":   "Maaf kara, samajle nahi. Mi sadhya phakt payment ani balance check madhye madat karu shakto.",
        "recipient_nf":     "Maaf kara, to contact sapadla nahi. Punha prayatna kara.",
        "amount_nu":        "Maaf kara, rakkam samajli nahi. Punha prayatna kara.",
        "mpin_setup":       "Ata keypad varun tumcha 4 ankee secret PIN set kara. Ha PIN tumhi nantar login sathi vaprala.",
        "mpin_confirm":     "Confirm karnyasathi, tumcha PIN punha taka.",
        "mpin_mismatch":    "PIN jullat nahi. Punha prayatna karu.",
        "contact_name":     "Tyanche naav kinva nate sanga. Udaharana: bhachya, mulgi.",
        "contact_number":   "Tyanche 10 ankee number sanga.",
        "contact_dtmf":     "Keypad var tyanche number taaka.",
        "contact_saved":    "Contact save zhala.",
        "enroll_retry":     "Awaz record karne madhe problem. Parat try kara.",
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
        "insufficient_balance": "Ya paymentsathi purava balance nahi.",
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
        "goodbye":           "SwaramPay vaparlyas abhar.",
        "error":             "Tantrik samasya.",
        "please_wait":       "Krupaya pratiksha kara.",
    },

    "bn": {
        "enter_phone":      "Apnar dosh sankhyar mobile number diun.",
        "enter_mpin":       "Apnar char sankhyar m PIN diun.",
        "wrong_mpin":       "Bhul m PIN. Abar cheshta korun.",
        "mpin_locked":      "Onek bhul cheshta. Call shesh hochche.",
        "no_account":       "Ei numbere kono account paoa jaaini.",
        "auth_success":     "Pramanikaran safal. SwaramPay-e swagato.",
        "how_can_i_help":   "Nomoshkar! Ami apnar ki shahajyo korte pari?",
        "who_to_pay":       "Kake taka pathate chan? Tar naam ba number bolun.",
        "how_much":         "Koto taka pathate chan?",
        "not_understood":   "Dukkhito, bujhte parini. Ami ekhon shudhu payment ar balance check e shahajjo korte pari.",
        "recipient_nf":     "Dukkhito, ei contact paoa jaini. Firey try korun.",
        "amount_nu":        "Dukkhito, porimaan bujhini. Firey try korun.",
        "mpin_setup":       "Ekhon keypad diye apnar 4 sankhyar secret PIN set korun. Eta apni pore login korte byabohar korben.",
        "mpin_confirm":     "Confirm korar jonno, apnar PIN abar din.",
        "mpin_mismatch":    "PIN mile ni. Abar shuru kori.",
        "contact_name":     "Oder naam ba sambondho bolun. Uddaharon: bhagne, meye.",
        "contact_number":   "Oder 10 sankhyar number bolun.",
        "contact_dtmf":     "Keypad e oder number din.",
        "contact_saved":    "Contact save hoyeche.",
        "enroll_retry":     "Awaz record korte problem hoyeche. Abar try korun.",
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
        "insufficient_balance": "Ei paymenter jonyo joththo balance nei.",
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
        "goodbye":           "SwaramPay baybaharer jonyo dhanyabaad.",
        "error":             "Tantrik samasya.",
        "please_wait":       "Doyakore apekkhaa korun.",
    },

    "gu": {
        "enter_phone":      "Krupa karine tamaro das anko no mobile number darj karo.",
        "enter_mpin":       "Krupa karine tamaro chaar anko no m PIN darj karo.",
        "wrong_mpin":       "Khoṭo m PIN. Pharthi prayas karo.",
        "mpin_locked":      "Ghano khoṭa prayaso. Kol paṭo thaay che.",
        "no_account":       "Aa number par khatu malyu nathi.",
        "auth_success":     "Pramanikaran saphal. SwaramPay ma aapnu swagat che.",
        "how_can_i_help":   "Namaste! Hu tamari kai rite madad kari shaku?",
        "who_to_pay":       "Konne paisa mokalva chhe? Tena naam athva number kaho.",
        "how_much":         "Ketla paisa mokalva chhe?",
        "not_understood":   "Maaf karo, samajyu nahi. Hu have payment ane balance check maa j madad kari shaku.",
        "recipient_nf":     "Maaf karo, e contact malyo nathi. Pharithi try karo.",
        "amount_nu":        "Maaf karo, raqam samajayi nathi. Pharithi try karo.",
        "mpin_setup":       "Have keypad thi tamaru 4 ank nu secret PIN set karo. Aa PIN tame pachhi thi login mate vaparso.",
        "mpin_confirm":     "Confirm karva mate, tamaru PIN pharithi nakho.",
        "mpin_mismatch":    "PIN match thayu nathi. Pharithi try karo.",
        "contact_name":     "Tena naam ke sambandh kaho. Uddaharan: bhatijo, dikri.",
        "contact_number":   "Tena 10 ank no number kaho.",
        "contact_dtmf":     "Keypad par tena number nakhho.",
        "contact_saved":    "Contact save thayo.",
        "enroll_retry":     "Awaj record karavama problem. Pharthi try karo.",
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
        "insufficient_balance": "Aa chukvani mate purtu balance nathi.",
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
        "goodbye":           "SwaramPay vaapravaa badal aabhar.",
        "error":             "Tantrik samasya.",
        "please_wait":       "Krupa karine raho.",
    },
}


# =============================================================================
# PART 4 — STATIC REGISTRATION / AUTH PROMPTS (pre-generated per language)
# Saves live TTS calls during enrollment (~20s saved per registration call)
# =============================================================================

# Import prompt dicts from app config
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from config import ENROLLMENT_PHRASES

STATIC_REGISTRATION_PROMPTS = {
    "hi": {
        "reg_name_prompt":   "Apna naam boliye.",
        "enroll_intro":      "Abhi hum aapki awaaz register karenge. Aapko teen waakyaan dohraaney honge. Har baar beep ke baad clearly boliye.",
        "guardian_prompt":   "Aapko ek SMS bheja gaya hai jisme companion portal ka link hai. Agar aap kisi guardian ko apne wallet mein paise daalne ki anumati dena chahte hain, toh unka 10 ank ka number abhi boliye. Nahi chahte toh chup rahiye.",
        "guardian_dtmf":     "Keypad se guardian ka 10 ank ka number daalen.",
        "auth_fail":         "Awaaz pehchaan teen baar mein nakaam rahi. Keypad PIN se try karein.",
        "auth_greet":        "Namaste! Apni awaaz se login karne ke liye yeh phrase dohraaiye:",
    },
    "en": {
        "reg_name_prompt":   "Please say your full name.",
        "enroll_intro":      "We will now register your voice. You will repeat three phrases. Please speak clearly after each beep.",
        "guardian_prompt":   "We have sent you an SMS with the companion portal link. If you would like to add a guardian who can add money to your wallet, please say their 10-digit number now. Otherwise stay silent.",
        "guardian_dtmf":     "Please enter the guardian's 10-digit number on the keypad.",
        "auth_fail":         "Voice authentication failed three times. Please use your keypad PIN instead.",
        "auth_greet":        "Welcome back! Please repeat the following phrase to log in:",
    },
    "ta": {
        "reg_name_prompt":   "Ungal peyar sollunga.",
        "enroll_intro":      "Ippodu ungal kural pothivom. Moondru vaarthaigalai thirumba solluveenga. Oru beep piragu thannai thendivu sollunga.",
        "guardian_prompt":   "Ungal SMS-il companion portal link anuppinoom. Guardian number solluvadhu virupthamana sollunga. Illatha podu maun aagidunga.",
        "guardian_dtmf":     "Guardian number keypad il type pannunga.",
        "auth_fail":         "Kural arival moonru murai thappu. Keypad PIN upayogippu.",
        "auth_greet":        "Vanakkam! Login seivatharku indha vaarthaigalai thirumba sollunga:",
    },
    "te": {
        "reg_name_prompt":   "Meeru peru cheppandi.",
        "enroll_intro":      "Ippudu meeru voice register cheyyabotunnam. Moodu phrases repeat cheyyandi. Prathi beep tarvata clearly maatladandi.",
        "guardian_prompt":   "Mee SMS ki companion portal link pathimamu. Guardian number cheppali ante cheppandi. Leda maatladakandi.",
        "guardian_dtmf":     "Keypad lo guardian number enter cheyyandi.",
        "auth_fail":         "Voice auth moodu saarlu fail. Keypad PIN vadakandi.",
        "auth_greet":        "Swaagatam! Login ki ee phrase repeat cheyyandi:",
    },
    "kn": {
        "reg_name_prompt":   "Nimma hesaru heli.",
        "enroll_intro":      "Ippaga nimma dhwani nondayisuvemu. Mooru vaakya punha heluvi. Pratii beep nantara sparshta vaagi heli.",
        "guardian_prompt":   "Companion portal link SMS madhye kalisiddeve. Guardian number helikollalu ichche iddare heli. Beda enandare sumu.",
        "guardian_dtmf":     "Keypad nadige guardian number enter madi.",
        "auth_fail":         "Voice auth moonru bari fail. Keypad PIN upayogisi.",
        "auth_greet":        "Swagata! Login ge ee phrase repeat madi:",
    },
    "ml": {
        "reg_name_prompt":   "Ningalude peru parayan.",
        "enroll_intro":      "Ippol ningalude shwaram register cheyyunnu. Moonnu vakyam repeat cheyyuka. Oru beep-inu sesham spashTamaai parayan.",
        "guardian_prompt":   "Companion portal link SMS il anachchu. Guardian number parayan virumbunaale parayan. Illa enkil maunam pal.",
        "guardian_dtmf":     "Guardian number keypadil type cheyyoo.",
        "auth_fail":         "Voice auth moonnu thavana fail. Keypad PIN upayogikku.",
        "auth_greet":        "Swagatam! Login cheyyaan ee phrase repeat cheyyoo:",
    },
    "mr": {
        "reg_name_prompt":   "Tumcha naav sanga.",
        "enroll_intro":      "Aata aapla awaz nondavuvat. Teen vakya punha sanga. Pratyeki beep nantar spashTa pane sanga.",
        "guardian_prompt":   "Companion portal link SMS madhye pathavala ahe. Guardian number sangayache asel tar sanga. Nahi tar gapp raha.",
        "guardian_dtmf":     "Guardian number keypad var enter kara.",
        "auth_fail":         "Voice auth tin velaa fail. Keypad PIN vaapra.",
        "auth_greet":        "Swagat! Login sathi ha phrase punha sanga:",
    },
    "bn": {
        "reg_name_prompt":   "Aapnar naam bolun.",
        "enroll_intro":      "Ekhon aapnar awaz nondhibon. Tin baky abar bolte hobe. Protibar beep er pore spashto kore bolun.",
        "guardian_prompt":   "Companion portal link SMS e pathano hoyeche. Guardian number bolte chan ta bolun. Nahole chup thakun.",
        "guardian_dtmf":     "Keypad e guardian number din.",
        "auth_fail":         "Voice auth teen bar fail. Keypad PIN byabohar korun.",
        "auth_greet":        "Swagoto! Login er jonyo ei phrase abar bolun:",
    },
    "gu": {
        "reg_name_prompt":   "Tamarun naam bolo.",
        "enroll_intro":      "Havan tamaro awaj nond karvaano. Teen vaakyo repeat karva. Ek beep pachi spashTa bolo.",
        "guardian_prompt":   "Companion portal link SMS ma mokli chhe. Guardian number keheva hoy to kaho. Na hoy to chup raho.",
        "guardian_dtmf":     "Keypad par guardian number nakhho.",
        "auth_fail":         "Voice auth tran vaar fail. Keypad PIN vaapo.",
        "auth_greet":        "Swagat! Login mate aa phrase repeat karo:",
    },
}

PHRASE_COUNT_PREFIX = {
    'hi': 'Vaakya', 'en': 'Phrase', 'ta': 'Vaarthai', 'te': 'Phrase',
    'kn': 'Vaakya', 'ml': 'Phrase', 'mr': 'Vaakya', 'bn': 'Vakya', 'gu': 'Vaakya',
}


def download_static_registration_prompts(force: bool = False) -> tuple[int, int]:
    """Pre-generate all static registration/auth prompts (name, enrollment, guardian)."""
    ok = 0
    fail = 0
    print("\n=== Static Registration Prompts ===")
    for lang, prompts in STATIC_REGISTRATION_PROMPTS.items():
        for key, text in prompts.items():
            out_path = PROMPT_DIR / f"{lang}_{key}.wav"
            if out_path.exists() and not force:
                print(f"  SKIP (exists): {out_path.name}")
                ok += 1
                continue
            print(f"  Generating: {out_path.name} ...", end=" ", flush=True)
            if save_tts(text, lang, out_path):
                print("OK")
                ok += 1
            else:
                print("FAIL")
                fail += 1

    print("\n=== Enrollment Phrases (0, 1, 2) per language ===")
    for lang, phrases in ENROLLMENT_PHRASES.items():
        prefix = PHRASE_COUNT_PREFIX.get(lang, 'Phrase')
        for idx in range(3):
            phrase = phrases[idx % len(phrases)]
            text = f"{prefix} {idx + 1}: {phrase}"
            out_path = PROMPT_DIR / f"{lang}_enroll_phrase_{idx}.wav"
            if out_path.exists() and not force:
                print(f"  SKIP (exists): {out_path.name}")
                ok += 1
                continue
            print(f"  Generating: {out_path.name} ...", end=" ", flush=True)
            if save_tts(text, lang, out_path):
                print("OK")
                ok += 1
            else:
                print("FAIL")
                fail += 1

    print("\n=== Auth Challenge Phrases (all, raw text, no prefix) per language ===")
    for lang, phrases in ENROLLMENT_PHRASES.items():
        for idx, phrase in enumerate(phrases):
            out_path = PROMPT_DIR / f"{lang}_auth_phrase_{idx}.wav"
            if out_path.exists() and not force:
                print(f"  SKIP (exists): {out_path.name}")
                ok += 1
                continue
            print(f"  Generating: {out_path.name} ...", end=" ", flush=True)
            if save_tts(phrase, lang, out_path):
                print("OK")
                ok += 1
            else:
                print("FAIL")
                fail += 1

    return ok, fail


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
    parser = argparse.ArgumentParser(description="Download SwaramPay IVR audio prompts via Sarvam AI TTS")
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
        ok, fail = download_static_registration_prompts(force=args.force)
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
