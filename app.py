"""
Streamlit app — Voorbladen invullen (Belisol PVC CERTIX)

Upload enkel de volgbladen-PDF. De app genereert automatisch de juiste voorbladen:
  • Ramen / kozijnen → één voorblad
  • Deuren           → apart voorblad (indien aanwezig)
Afwijkingen per element worden in rood vermeld in Vak B van het volgblad.
Vervolgbladen worden automatisch gekoppeld aan hun hoofdblad.
Stuks > 1 worden gedupliceerd in de output.

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
    doc      = fitz.open(stream=data, filetype="pdf")
    header   = pv.extraheer_header_uit_volgblad(doc[0])
    specs    = [pv.parse_volgblad(doc[i]) for i in range(len(doc))]
    elementen = pv.verdeel_in_elementen(specs)   # [{spec, paginas}]
    groepen   = pv.groepeer_volgbladen(specs)
    return header, specs, elementen, groepen


header, specs, elementen, groepen = _parse(pdf_bytes)

if not specs:
    st.error("Geen volgbladen gevonden in dit PDF.")
    st.stop()

# ── 3. Samenvatting tonen ─────────────────────────────────────────────────────
st.subheader("📋 Gevonden elementen")

for groep_naam, groep_idx in groepen:
    groep_idx_set = set(groep_idx)
    groep_specs   = [specs[i] for i in groep_idx]
    groep_spec    = pv.bepaal_groep_spec(groep_specs)

    # Elementen die tot deze groep behoren (hoofdbladen)
    groep_elementen = [
        el for el in elementen if el['paginas'][0] in groep_idx_set
    ]

    n_stuks_totaal = sum(el['spec'].get('stuks', 1) for el in groep_elementen)

    with st.expander(
        f"**{groep_naam}** — {len(groep_elementen)} element(en), "
        f"{n_stuks_totaal} stuk(s) totaal → 1 voorblad",
        expanded=True,
    ):
        col1, col2, col3 = st.columns(3)
        col1.metric("Glas",    groep_spec.get("glas_str")    or "—")
        col2.metric("Profiel", groep_spec.get("profiel_type") or "—")
        col3.metric("Kleur kader", groep_spec.get("kader_buiten") or "—")

        for el in groep_elementen:
            i         = el['paginas'][0]   # hoofdblad index
            stuks     = el['spec'].get('stuks', 1)
            afw       = pv.zoek_afwijkingen(el['spec'], groep_spec)
            et        = el['spec'].get('element_type', f'Volgblad {i+1}')
            pos_match = __import__('re').search(
                r'POS\.\s*[\d.]+[A-Z]?', specs[i].get('element_type', ''),
            )
            # Label ophalen uit pagina tekst
            doc_tmp = fitz.open(stream=pdf_bytes, filetype="pdf")
            regels  = [r.strip() for r in doc_tmp[i].get_text("text").split("\n") if r.strip()]
            label   = next((r for r in regels if r.startswith("POS.")), f"Volgblad {i+1}")

            label_met_stuks = f"{label}  ×{stuks}" if stuks > 1 else label
            n_vervolgbladen = len(el['paginas']) - 1

            if afw:
                extra_lbl = f"  _(+{n_vervolgbladen} vervolgblad)_" if n_vervolgbladen else ""
                afw_lijst = "\n".join(f"- {a}" for a in afw)
                st.warning(f"⚠️ **{label_met_stuks}**{extra_lbl}\n\n{afw_lijst}")
            else:
                extra = f"  _(+{n_vervolgbladen} vervolgblad)_" if n_vervolgbladen else ""
                st.caption(f"✓ {label_met_stuks} — conform voorblad{extra}")

st.divider()

# ── 4. PM-maaten invoeren ─────────────────────────────────────────────────────
st.subheader("📐 Productiemaaten (PM)")
st.caption(
    "Vul de productiemaat in per element. "
    "De offertemaat staat als hint. Leeg laten = niet invullen."
)

pm_invoer: dict[int, dict] = {}
for el in elementen:
    if el['spec'].get('is_vervolgblad'):
        continue   # vervolgbladen krijgen geen PM-invoer

    i            = el['paginas'][0]
    breedte_hint = el['spec'].get('offer_breedte')
    hoogte_hint  = el['spec'].get('offer_hoogte')

    doc_tmp = fitz.open(stream=pdf_bytes, filetype="pdf")
    regels  = [r.strip() for r in doc_tmp[i].get_text("text").split("\n") if r.strip()]
    label   = next((r for r in regels if r.startswith("POS.")), f"Volgblad {i+1}")

    b_placeholder = str(breedte_hint) if breedte_hint else "bijv. 980"
    h_placeholder = str(hoogte_hint)  if hoogte_hint  else "bijv. 2290"

    col1, col2, col3 = st.columns([3, 2, 2])
    col1.markdown(f"**{label}**")
    b = col2.text_input(
        "Breedte (mm)", key=f"pm_b_{i}",
        placeholder=b_placeholder, label_visibility="collapsed",
    )
    h = col3.text_input(
        "Hoogte (mm)", key=f"pm_h_{i}",
        placeholder=h_placeholder, label_visibility="collapsed",
    )
    pm_invoer[i] = {"breedte": b.strip(), "hoogte": h.strip()}

st.divider()

# ── 5. Optionele maataanpassingen tekening ────────────────────────────────────
with st.expander("🔧 Maataanpassingen in tekeningen *(optioneel)*", expanded=False):
    st.caption("Leeg laten = geen wijziging. Formaat: oud=nieuw  (bijv. 980=1080)")
    maat_invoer: dict[int, dict] = {}
    for el in elementen:
        if el['spec'].get('is_vervolgblad'):
            continue
        i = el['paginas'][0]
        doc_tmp = fitz.open(stream=pdf_bytes, filetype="pdf")
        regels  = [r.strip() for r in doc_tmp[i].get_text("text").split("\n") if r.strip()]
        label   = next((r for r in regels if r.startswith("POS.")), f"Volgblad {i+1}")

        col1, col2, col3 = st.columns([2, 2, 2])
        col1.markdown(f"**{label}**")
        b = col2.text_input("Breedte", key=f"b_{i}", placeholder="bijv. 980=1080",  label_visibility="collapsed")
        h = col3.text_input("Hoogte",  key=f"h_{i}", placeholder="bijv. 2290=2390", label_visibility="collapsed")
        maat_invoer[i] = {"breedte": b.strip(), "hoogte": h.strip()}

st.divider()

# ── 6. Genereren ──────────────────────────────────────────────────────────────
if not st.button("✅ Genereer voorbladen", type="primary", use_container_width=True):
    st.stop()

with st.spinner("PDF wordt gegenereerd…"):

    vb_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    result = fitz.open()

    for groep_naam, groep_idx in groepen:
        groep_idx_set   = set(groep_idx)
        groep_specs     = [specs[i] for i in groep_idx]
        groep_spec      = pv.bepaal_groep_spec(groep_specs)
        groep_elementen = [el for el in elementen if el['paginas'][0] in groep_idx_set]

        # Voorblad genereren
        voorblad_doc = pv.vul_voorblad(header, groep_spec)
        result.insert_pdf(voorblad_doc)

        for el in groep_elementen:
            stuks       = el['spec'].get('stuks', 1)
            hoofd_idx   = el['paginas'][0]
            vervolg_idx = el['paginas'][1:]

            # Verzamel gefilterde tekst van vervolgbladen
            extra_regels = []
            for vi in vervolg_idx:
                extra_regels.extend(pv.extraheer_regels_vervolgblad(vb_doc[vi]))

            # Verwerk het HOOFDBLAD
            hoofd = vb_doc[hoofd_idx]

            # Maataanpassingen tekening
            w = maat_invoer.get(hoofd_idx, {})
            for invoer, zone in ((w.get("breedte", ""), "bottom"),
                                 (w.get("hoogte",  ""), "right")):
                if invoer and "=" in invoer:
                    try:
                        oud, nieuw = [int(x.strip()) for x in invoer.split("=", 1)]
                        pv.wijzig_maat_in_tekening(hoofd, oud, nieuw, zone=zone)
                    except ValueError:
                        pass

            # PM-maat invullen op het hoofdblad
            pm = pm_invoer.get(hoofd_idx, {})
            try:
                b_pm = int(pm.get("breedte") or 0)
                h_pm = int(pm.get("hoogte")  or 0)
                if b_pm and h_pm:
                    pv.schrijf_pm_maat(hoofd, b_pm, h_pm)
            except ValueError:
                pass

            # Afwijkingen + Vak B opschonen + extra tekst van vervolgbladen
            afwijkingen = pv.zoek_afwijkingen(specs[hoofd_idx], groep_spec)
            pv.process_volgblad(hoofd, afwijkingen, extra_regels=extra_regels)

            # Voeg ALLEEN het hoofdblad toe (stuks keer), vervolgbladen worden weggelaten
            for _ in range(stuks):
                result.insert_pdf(vb_doc, from_page=hoofd_idx, to_page=hoofd_idx)

    pv.voeg_paginanummers_toe(result)

    buf = io.BytesIO()
    result.save(buf)
    buf.seek(0)

# ── 7. Download ───────────────────────────────────────────────────────────────
n_voorbladen     = len(groepen)
totaal_volgbladen = sum(
    el['spec'].get('stuks', 1) for el in elementen if not el['spec'].get('is_vervolgblad')
)
st.success(
    f"✅ Klaar — {n_voorbladen} voorblad(en), "
    f"{totaal_volgbladen} volgblad(en) in output"
)

output_naam = Path(uploaded.name).stem + "_ingevuld.pdf"
st.download_button(
    label="⬇️ Download ingevuld PDF",
    data=buf,
    file_name=output_naam,
    mime="application/pdf",
    use_container_width=True,
    type="primary",
)

# ── 8. Preview ────────────────────────────────────────────────────────────────
st.divider()
st.subheader("👁 Preview")

preview_doc = fitz.open(stream=buf.getvalue(), filetype="pdf")
n_pages = len(preview_doc)

for row_start in range(0, n_pages, 2):
    cols = st.columns(2)
    for ci in range(2):
        pi = row_start + ci
        if pi >= n_pages:
            break
        page = preview_doc[pi]
        pix  = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        cols[ci].image(
            pix.tobytes("png"),
            caption=f"P: {pi + 1}/{n_pages}",
            use_container_width=True,
        )
