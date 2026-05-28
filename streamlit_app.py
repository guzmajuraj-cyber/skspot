import streamlit as str
import pandas as pd
from decimal import Decimal
import datetime

# --- KONFIGURÁCIA STRÁNKY ---
st.set_page_config(
    page_title="SpotCheck Slovensko",
    page_icon="⚡",
    layout="wide"
)

# --- CSS ŠTÝLY PRE KRAJŠÍ DIZAJN ---
st.markdown("""
<style>
    .main-title {
        font-size: 2.5rem;
        font-weight: 800;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.1rem;
        color: #4B5563;
        margin-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# --- HLAVNÉ ROZHRANIE ---
st.markdown('<div class="main-title">⚡ SpotCheck Slovensko</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Porovnanie fixných a reálnych spotových cien z OKTE.</div>', unsafe_allow_html=True)

# --- BOČNÝ PANEL (SIDEBAR) ---
st.sidebar.header("⚙️ Nastavenia")

# Premenovaný parameter pre fixnú cenu
cena_fix_input = st.sidebar.slider("Vaša cena silovej zložky bez distribúcie (centov / kWh)", 10.0, 25.0, 16.5, 0.5)
cena_fix_eur = Decimal(str(cena_fix_input)) / Decimal('100.0')

# Odstránený slider marže - parameter je interne nastavený na 0
marza_dodavatela = Decimal('0.0')

# --- DEFINÍCIA ZÁLOŽIEK (TABS) ---
tabs = st.tabs([
    "📊 Analýza a Porovnanie", 
    "👀 Kontrola načítaných dát", 
    "💡 Ako získať dáta?", 
    "📅 Denné ceny OKTE", 
    "💬 Spätná väzba"
])

# --- TAB 0: ANALÝZA A POROVNANIE ---
with tabs[0]:
    st.write("### 📊 Analýza a Porovnanie spotreby")
    st.info("Tu bude prebiehať hlavný výpočet a vizualizácia po nahratí dát.")
    # Miesto pre tvoju logiku analýzy, grafov a výpočtov...

# --- TAB 1: KONTROLA NAČÍTANÝCH DÁT ---
with tabs[1]:
    st.write("### 👀 Kontrola načítaných dát")
    st.info("Po nahratí súboru tu uvidíte surové dáta pripravené na spracovanie.")
    # Miesto pre st.dataframe() nahranných dát...

# --- TAB 2: AKO ZÍSKAŤ DÁTA? ---
with tabs[2]:
    st.write("### 💡 Ako získať dáta o spotrebe?")
    st.markdown("""
    Pre správne fungovanie aplikácie potrebujete hodinové dáta o vašej spotrebe (priebehové meranie).
    Tie si môžete stiahnuť z portálu vášho prevádzkovateľa distribučnej sústavy (ZSD, SSD, VSD) alebo od vášho dodávateľa.
    """)

# --- TAB 3: DENNÉ CENY OKTE ---
with tabs[3]:
    st.write("### 📅 Denné ceny OKTE")
    st.info("Prehľad aktuálnych spotových cien na slovenskom trhu pre zvolený deň.")
    # Miesto pre načítanie a zobrazenie cien z OKTE API/webu...

# --- TAB 4: SPÄTNÁ VÄZBA ---
with tabs[4]:
    st.write("### 💬 Nápady, vylepšenia a spätná väzba")
    st.write("Našli ste v aplikácii chybu, nesedia vám výpočty s faktúrou alebo by ste chceli doplniť novú funkciu? Napíšte mi.")
    
    # HTML kód spojený do jedného riadku – vyčistený od neaktívneho poľa, štýlovaný priamo vo <form>
    form_html_jednoradkovy = (
        '<form action="https://formsubmit.co/guzmajuraj@gmail.com" method="POST" style="background-color: #F9FAFB; padding: 2rem; border-radius: 0.5rem; border: 1px solid #E5E7EB; max-width: 600px;">'
        '<input type="hidden" name="_subject" value="SpotCheck SK - Nova spatna vazba!">'
        '<input type="hidden" name="_honeypot" style="display:none">'
        '<label style="font-weight: 600; color: #374151; font-family: inherit;">Váš e-mail (nepovinné, pre odpoveď):</label><br>'
        '<input type="email" name="email" placeholder="napr. jozef@gmail.com" style="width: 100%; padding: 0.6rem; margin-top: 0.3rem; margin-bottom: 1.2rem; border: 1px solid #D1D5DB; border-radius: 0.375rem; font-family: inherit; font-size: 0.95rem;"><br>'
        '<label style="font-weight: 600; color: #374151; font-family: inherit;">Vaša správa alebo postreh:</label><br>'
        '<textarea name="message" rows="5" required placeholder="Napíšte sem váš komentár, nápad na vylepšenie..." style="width: 100%; padding: 0.6rem; margin-top: 0.3rem; margin-bottom: 1.2rem; border: 1px solid #D1D5DB; border-radius: 0.375rem; font-family: inherit; font-size: 0.95rem; resize: vertical;"></textarea><br>'
        '<button type="submit" style="background-color: #1E3A8A; color: white; border: none; padding: 0.7rem 1.5rem; font-weight: bold; border-radius: 0.375rem; cursor: pointer; font-family: inherit; font-size: 0.95rem; transition: background-color 0.2s;" onmouseover="this.style.backgroundColor=\'#1D4ED8\'" onmouseout="this.style.backgroundColor=\'#1E3A8A\'">✉️ Odoslať správu</button>'
        '</form>'
    )
    
    # Vykreslenie vyčisteného formulára
    st.markdown(form_html_jednoradkovy, unsafe_allow_html=True)
    
    # Alternatívny mailto odkaz pod boxom
    st.write("")
    st.write("---")
    st.write("Alternatívne mi môžete poslať e-mail priamo z vašej poštovej schránky:")
    
    mailto_url = "mailto:guzmajuraj@gmail.com?subject=SpotCheck%20SK%20-%20Sp%C3%A4tn%C3%A1%20v%C3%A4zba&body=Ahoj%20Juraj,%20m%C3%A1m%20nasledovn%C3%BD%20postreh%20k%20aplik%C3%A1cii:%20"
    st.markdown(f'<a href="{mailto_url}" target="_blank" style="text-decoration: none;"><button style="background-color: #F3F4F6; color: #1F2937; border: 1px solid #D1D5DB; padding: 0.5rem 1rem; border-radius: 0.375rem; font-weight: 500; cursor: pointer; font-family: inherit;">📧 Otvoriť môj e-mailový program</button></a>', unsafe_allow_html=True)
