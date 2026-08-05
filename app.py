"""
Streamlit app — Voorbladen invullen (Belisol PVC CERTIX)

Upload de volgbladen-PDF. De app genereert automatisch de voorbladen.

Starten:
    streamlit run app.py
"""

import base64
import io
import sys
from pathlib import Path

import fitz
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent))
import process_voorblad as pv

# ── Pagina-instellingen ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Voorbladen invullen",
    page_icon="🏠",
    layout="wide",
)

# ── Session state ──────────────────────────────────────────────────────────────
if 'preview_page'     not in st.session_state: st.session_state.preview_page     = 0
if 'last_upload_name' not in st.session_state: st.session_state.last_upload_name = None


# ── Gecachte functies (module-niveau) ─────────────────────────────────────────
@st.cache_data(show_spinner="Volgbladen lezen…")
def _parse(data: bytes):
    doc      = fitz.open(stream=data, filetype="pdf")
    header   = pv.extraheer_header_uit_volgblad(doc[0])
    specs    = [pv.parse_volgblad(doc[i]) for i in range(len(doc))]
    elementen = pv.verdeel_in_elementen(specs)
    groepen   = pv.groepeer_volgbladen(specs)
    return header, specs, elementen, groepen


@st.cache_data(show_spinner="Voorbladen genereren…")
def _genereer(pdf_bytes: bytes, pm_frozen: tuple, maat_frozen: tuple) -> bytes:
    """Genereert de ingevulde PDF. Gecached op basis van alle inputs."""
    header, specs, elementen, groepen = _parse(pdf_bytes)

    # pm_frozen / maat_frozen → dict reconstrueren
    pm_invoer   = {k: {'breedte': b, 'hoogte': h} for k, b, h in pm_frozen}
    maat_invoer = {k: {'breedte': b, 'hoogte': h} for k, b, h in maat_frozen}

    vb_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    result = fitz.open()

    for groep_naam, groep_idx in groepen:
        groep_idx_set   = set(groep_idx)
        groep_specs     = [specs[i] for i in groep_idx]
        groep_spec      = pv.bepaal_groep_spec(groep_specs)
        groep_elementen = [el for el in elementen if el['paginas'][0] in groep_idx_set]

        voorblad_doc = pv.vul_voorblad(header, groep_spec)
        result.insert_pdf(voorblad_doc)

        for el in groep_elementen:
            stuks       = el['spec'].get('stuks', 1)
            hoofd_idx   = el['paginas'][0]
            vervolg_idx = el['paginas'][1:]

            extra_regels = []
            for vi in vervolg_idx:
                extra_regels.extend(pv.extraheer_regels_vervolgblad(vb_doc[vi]))

            hoofd = vb_doc[hoofd_idx]

            w = maat_invoer.get(hoofd_idx, {})
            for invoer, zone in ((w.get('breedte', ''), 'bottom'),
                                 (w.get('hoogte',  ''), 'right')):
                if invoer and '=' in invoer:
                    try:
                        oud, nieuw = [int(x.strip()) for x in invoer.split('=', 1)]
                        pv.wijzig_maat_in_tekening(hoofd, oud, nieuw, zone=zone)
                    except ValueError:
                        pass

            pm = pm_invoer.get(hoofd_idx, {})
            try:
                b_pm = int(pm.get('breedte') or 0)
                h_pm = int(pm.get('hoogte')  or 0)
                if b_pm and h_pm:
                    pv.schrijf_pm_maat(hoofd, b_pm, h_pm)
            except ValueError:
                pass

            afwijkingen = pv.zoek_afwijkingen(specs[hoofd_idx], groep_spec)
            pv.process_volgblad(hoofd, afwijkingen, extra_regels=extra_regels)

            for _ in range(stuks):
                result.insert_pdf(vb_doc, from_page=hoofd_idx, to_page=hoofd_idx)

    pv.voeg_paginanummers_toe(result)

    buf = io.BytesIO()
    result.save(buf)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def _render_pages(data: bytes, scale: float = 1.3):
    doc = fitz.open(stream=data, filetype="pdf")
    mat = fitz.Matrix(scale, scale)
    return [doc[i].get_pixmap(matrix=mat).tobytes("png") for i in range(len(doc))]


# ── Titel ─────────────────────────────────────────────────────────────────────
st.title("🏠 Voorbladen invullen")
st.caption("Belisol PVC CERTIX — upload de volgbladen, de app genereert automatisch de voorbladen")

left, right = st.columns([2, 3], gap="large")

# ══════════════════════════════════════════════════════════════════════════════
# LINKER KOLOM — controls
# ══════════════════════════════════════════════════════════════════════════════
with left:
    st.divider()

    # 1. Upload ────────────────────────────────────────────────────────────────
    uploaded = st.file_uploader(
        "Upload volgbladen PDF",
        type="pdf",
        help="PDF met alleen de volgbladen (technische fiches per element)",
    )

    if uploaded is not None:
        if st.session_state.last_upload_name != uploaded.name:
            st.session_state.preview_page    = 0
            st.session_state.last_upload_name = uploaded.name
    else:
        st.session_state.last_upload_name = None

    if uploaded is None:
        st.info("Upload een PDF met volgbladen om te beginnen.")

    else:
        pdf_bytes = uploaded.getvalue()
        header, specs, elementen, groepen = _parse(pdf_bytes)

        if not specs:
            st.error("Geen volgbladen gevonden in dit PDF.")

        else:
            # 2. Samenvatting ──────────────────────────────────────────────────
            st.subheader("📋 Gevonden elementen")

            for groep_naam, groep_idx in groepen:
                groep_idx_set   = set(groep_idx)
                groep_specs     = [specs[i] for i in groep_idx]
                groep_spec      = pv.bepaal_groep_spec(groep_specs)
                groep_elementen = [el for el in elementen if el['paginas'][0] in groep_idx_set]
                n_stuks_totaal  = sum(el['spec'].get('stuks', 1) for el in groep_elementen)

                with st.expander(
                    f"**{groep_naam}** — {len(groep_elementen)} element(en), "
                    f"{n_stuks_totaal} stuk(s) totaal → 1 voorblad",
                    expanded=True,
                ):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Glas",        groep_spec.get("glas_str")    or "—")
                    c2.metric("Profiel",     groep_spec.get("profiel_type") or "—")
                    c3.metric("Kleur kader", groep_spec.get("kader_buiten") or "—")

                    for el in groep_elementen:
                        i     = el['paginas'][0]
                        stuks = el['spec'].get('stuks', 1)
                        afw   = pv.zoek_afwijkingen(el['spec'], groep_spec)

                        doc_tmp = fitz.open(stream=pdf_bytes, filetype="pdf")
                        regels  = [r.strip() for r in doc_tmp[i].get_text("text").split("\n") if r.strip()]
                        label   = next((r for r in regels if r.startswith("POS.")), f"Volgblad {i+1}")
                        label_met_stuks = f"{label}  ×{stuks}" if stuks > 1 else label
                        n_verv  = len(el['paginas']) - 1

                        if afw:
                            extra_lbl = f"  _(+{n_verv} vervolgblad)_" if n_verv else ""
                            afw_lijst = "\n".join(f"- {a}" for a in afw)
                            st.warning(f"⚠️ **{label_met_stuks}**{extra_lbl}\n\n{afw_lijst}")
                        else:
                            extra = f"  _(+{n_verv} vervolgblad)_" if n_verv else ""
                            st.caption(f"✓ {label_met_stuks} — conform voorblad{extra}")

            st.divider()

            # 3. PM-maaten ─────────────────────────────────────────────────────
            st.subheader("📐 Productiemaaten (PM)")
            st.caption("Optioneel. De preview past automatisch aan.")

            pm_invoer: dict[int, dict] = {}
            for el in elementen:
                if el['spec'].get('is_vervolgblad'):
                    continue
                i            = el['paginas'][0]
                breedte_hint = el['spec'].get('offer_breedte')
                hoogte_hint  = el['spec'].get('offer_hoogte')

                doc_tmp = fitz.open(stream=pdf_bytes, filetype="pdf")
                regels  = [r.strip() for r in doc_tmp[i].get_text("text").split("\n") if r.strip()]
                label   = next((r for r in regels if r.startswith("POS.")), f"Volgblad {i+1}")

                b_ph = str(breedte_hint) if breedte_hint else "bijv. 980"
                h_ph = str(hoogte_hint)  if hoogte_hint  else "bijv. 2290"

                cc1, cc2, cc3 = st.columns([3, 2, 2])
                cc1.markdown(f"**{label}**")
                b = cc2.text_input("B", key=f"pm_b_{i}", placeholder=b_ph, label_visibility="collapsed")
                h = cc3.text_input("H", key=f"pm_h_{i}", placeholder=h_ph, label_visibility="collapsed")
                pm_invoer[i] = {"breedte": b.strip(), "hoogte": h.strip()}

            # 4. Maataanpassingen (optioneel) ──────────────────────────────────
            st.divider()
            maat_invoer: dict[int, dict] = {}
            with st.expander("🔧 Maataanpassingen in tekeningen *(optioneel)*", expanded=False):
                st.caption("Leeg laten = geen wijziging. Formaat: oud=nieuw  (bijv. 980=1080)")
                for el in elementen:
                    if el['spec'].get('is_vervolgblad'):
                        continue
                    i = el['paginas'][0]
                    doc_tmp = fitz.open(stream=pdf_bytes, filetype="pdf")
                    regels  = [r.strip() for r in doc_tmp[i].get_text("text").split("\n") if r.strip()]
                    label   = next((r for r in regels if r.startswith("POS.")), f"Volgblad {i+1}")
                    cc1, cc2, cc3 = st.columns([2, 2, 2])
                    cc1.markdown(f"**{label}**")
                    b = cc2.text_input("B", key=f"b_{i}",  placeholder="bijv. 980=1080",  label_visibility="collapsed")
                    h = cc3.text_input("H", key=f"h_{i}",  placeholder="bijv. 2290=2390", label_visibility="collapsed")
                    maat_invoer[i] = {"breedte": b.strip(), "hoogte": h.strip()}

            st.divider()

            # 5. Auto-genereren + download ────────────────────────────────────
            pm_frozen   = tuple(sorted((k, d['breedte'], d['hoogte']) for k, d in pm_invoer.items()))
            maat_frozen = tuple(sorted((k, d['breedte'], d['hoogte']) for k, d in maat_invoer.items()))
            generated_bytes = _genereer(pdf_bytes, pm_frozen, maat_frozen)

            n_vb  = len(groepen)
            n_vlg = sum(
                el['spec'].get('stuks', 1) for el in elementen
                if not el['spec'].get('is_vervolgblad')
            )
            st.caption(f"{n_vb} voorblad(en) · {n_vlg} volgblad(en) · {len(generated_bytes) // 1024} KB")

            output_naam = Path(uploaded.name).stem + "_ingevuld.pdf"
            st.download_button(
                label="⬇️ Download ingevuld PDF",
                data=generated_bytes,
                file_name=output_naam,
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )


# ══════════════════════════════════════════════════════════════════════════════
# RECHTER KOLOM — live preview
# ══════════════════════════════════════════════════════════════════════════════
with right:
    if uploaded is not None and specs and generated_bytes is not None:
        st.subheader("📄 Preview — Ingevuld PDF")

        pages   = _render_pages(generated_bytes)
        n_pages = len(pages)
        current = max(0, min(st.session_state.preview_page, n_pages - 1))

        # Navigatiebalk ────────────────────────────────────────────────────────
        nav1, nav2, nav3, nav4 = st.columns([1, 1, 3, 1])
        if nav1.button("◀", key="prev_btn", use_container_width=True, disabled=(current == 0)):
            st.session_state.preview_page = current - 1
            st.rerun()
        if nav2.button("▶", key="next_btn", use_container_width=True, disabled=(current == n_pages - 1)):
            st.session_state.preview_page = current + 1
            st.rerun()
        nav3.markdown(
            f"<div style='padding-top:6px; color:#555;'>Pagina <b>{current + 1}</b> / {n_pages}</div>",
            unsafe_allow_html=True,
        )
        pdf_b64 = base64.b64encode(generated_bytes).decode()
        nav4.markdown(
            f'<a href="data:application/pdf;base64,{pdf_b64}" target="_blank" rel="noopener" '
            f'style="display:block; text-align:center; padding:6px 0; background:#f0f2f6; '
            f'border-radius:6px; text-decoration:none; color:#333; font-size:16px;" '
            f'title="Openen in nieuw tabblad">⛶</a>',
            unsafe_allow_html=True,
        )

        # Scrollbare container met alle pagina's ──────────────────────────────
        with st.container(height=780, border=True):
            for i, img_bytes in enumerate(pages):
                if i == current:
                    st.markdown(
                        '<div style="outline:3px solid #1f77b4; border-radius:4px; '
                        'margin-bottom:6px; padding:2px;">',
                        unsafe_allow_html=True,
                    )
                st.image(img_bytes, caption=f"P: {i + 1} / {n_pages}", use_container_width=True)
                if i == current:
                    st.markdown('</div>', unsafe_allow_html=True)

        # Pijltjestoetsen ──────────────────────────────────────────────────────
        components.html(
            """
            <script>
            (function() {
                function clickBtn(label) {
                    var btns = window.parent.document.querySelectorAll('button');
                    for (var b of btns) {
                        if (b.textContent.trim() === label) { b.click(); return; }
                    }
                }
                window.parent.document.addEventListener('keydown', function(e) {
                    if (e.key === 'ArrowLeft')  clickBtn('◀');
                    if (e.key === 'ArrowRight') clickBtn('▶');
                });
            })();
            </script>
            """,
            height=0,
        )

    elif uploaded is not None:
        st.info("Preview wordt geladen…")
