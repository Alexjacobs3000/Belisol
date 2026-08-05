"""
Streamlit app — Voorbladen invullen (Belisol PVC CERTIX)

Upload enkel de volgbladen-PDF. De app genereert automatisch de juiste voorbladen:
  • Ramen / kozijnen → één voorblad
  • Deuren           → apart voorblad (indien aanwezig)
Afwijkingen per element worden in rood vermeld in Vak B van het volgblad.

Starten:
    streamlit run app.py
"""

import io
import sys
from pathlib import Path

import fitz
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import process_voorblad as pv

# ── Pagina-instellingen ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Voorbladen invullen",
    page_icon="🏠",
    layout="centered",
)

st.title("🏠 Voorbladen invullen")
st.caption("Belisol PVC CERTIX — upload de volgbladen, de app genereert automatisch de voorbladen")

st.divider()

# ── 1. PDF uploaden ───────────────────────────────────────────────────────────
uploaded = st.file_uploader(
    "Upload volgbladen PDF",
    type="pdf",
    help="PDF met alleen de volgbladen (technische fiches per element)",
)

if not uploaded:
    st.stop()

pdf_bytes = uploaded.getvalue()


# ── 2. PDF parsen ─────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Volgbladen lezen…")
def _parse(data: bytes):
    doc    = fitz.open(stream=data, filetype="pdf")
    header = pv.extraheer_header_uit_volgblad(doc[0])
    specs  = [pv.parse_volgblad(doc[i]) for i in range(len(doc))]
    labels = []
    for i in range(len(doc)):
        regels = [r.strip() for r in doc[i].get_text("text").split("\n") if r.strip()]
        label  = next((r for r in regels if r.startswith("POS.")), f"Volgblad {i + 1}")
        labels.append(label)
    groepen = pv.groepeer_volgbladen(specs)
    return header, specs, labels, groepen


header, specs, pos_labels, groepen = _parse(pdf_bytes)

if not specs:
    st.error("Geen volgbladen gevonden in dit PDF.")
    st.stop()

# ── 3. Samenvatting tonen ─────────────────────────────────────────────────────
st.subheader("📋 Gevonden elementen")

for groep_naam, groep_idx in groepen:
    groep_specs = [specs[i] for i in groep_idx]
    groep_spec  = pv.bepaal_groep_spec(groep_specs)

    with st.expander(
        f"**{groep_naam}** — {len(groep_idx)} element(en) → 1 voorblad",
        expanded=True,
    ):
        # Toon consensus-waarden
        col1, col2, col3 = st.columns(3)
        col1.metric("Glas",    groep_spec.get("glas_str")    or "—")
        col2.metric("Profiel", groep_spec.get("profiel_type") or "—")
        col3.metric("Kleur kader", groep_spec.get("kader_buiten") or "—")

        # Toon elementen met eventuele afwijkingen
        for i in groep_idx:
            afw = pv.zoek_afwijkingen(specs[i], groep_spec)
            label = pos_labels[i]
            if afw:
                st.warning(f"⚠️ **{label}** — afwijkingen: {', '.join(afw)}")
            else:
                st.caption(f"✓ {label} — conform voorblad")

st.divider()

# ── 4. Optionele maataanpassingen ─────────────────────────────────────────────
with st.expander("📐 Maataanpassingen in tekeningen *(optioneel)*", expanded=False):
    st.caption("Leeg laten = geen wijziging. Formaat: oud=nieuw  (bijv. 980=1080)")
    maat_invoer: dict[int, dict] = {}
    for idx, label in enumerate(pos_labels):
        col1, col2, col3 = st.columns([2, 2, 2])
        col1.markdown(f"**{label}**")
        b = col2.text_input("Breedte", key=f"b_{idx}", placeholder="bijv. 980=1080",  label_visibility="collapsed")
        h = col3.text_input("Hoogte",  key=f"h_{idx}", placeholder="bijv. 2290=2390", label_visibility="collapsed")
        maat_invoer[idx] = {"breedte": b.strip(), "hoogte": h.strip()}

st.divider()

# ── 5. Genereren ──────────────────────────────────────────────────────────────
if not st.button("✅ Genereer voorbladen", type="primary", use_container_width=True):
    st.stop()

with st.spinner("PDF wordt gegenereerd…"):

    vb_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    result = fitz.open()

    for groep_naam, groep_idx in groepen:
        groep_specs = [specs[i] for i in groep_idx]
        groep_spec  = pv.bepaal_groep_spec(groep_specs)

        # Voorblad genereren
        voorblad_doc = pv.vul_voorblad(header, groep_spec)
        result.insert_pdf(voorblad_doc)

        # Volgbladen verwerken
        for i in groep_idx:
            page = vb_doc[i]

            # Maataanpassingen
            w = maat_invoer.get(i, {})
            for invoer, zone in ((w.get("breedte", ""), "bottom"),
                                 (w.get("hoogte",  ""), "right")):
                if invoer and "=" in invoer:
                    try:
                        oud, nieuw = [int(x.strip()) for x in invoer.split("=", 1)]
                        pv.wijzig_maat_in_tekening(page, oud, nieuw, zone=zone)
                    except ValueError:
                        pass

            # Afwijkingen bepalen + Vak B opschonen
            afwijkingen = pv.zoek_afwijkingen(specs[i], groep_spec)
            pv.process_volgblad(page, afwijkingen)

            result.insert_pdf(vb_doc, from_page=i, to_page=i)

    buf = io.BytesIO()
    result.save(buf)
    buf.seek(0)

# ── 6. Download ───────────────────────────────────────────────────────────────
n_voorbladen = len(groepen)
st.success(f"✅ Klaar — {n_voorbladen} voorblad(en) gegenereerd voor {len(specs)} element(en)")

output_naam = Path(uploaded.name).stem + "_ingevuld.pdf"
st.download_button(
    label="⬇️ Download ingevuld PDF",
    data=buf,
    file_name=output_naam,
    mime="application/pdf",
    use_container_width=True,
    type="primary",
)
