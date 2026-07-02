/* dashboard.js — filtro en tiempo real + paginación del inventario. */

const rows = Array.from(document.querySelectorAll('#tbl tbody tr[data-q]'));
const cnt  = document.getElementById('cnt');
const PAGE_SIZE = 25;
let currentPage = 1;
let filtered = rows.slice();

function filtrar(){
    const q   = document.getElementById('q').value.toLowerCase().trim();
    const cat = document.getElementById('fCat').value;
    const est = document.getElementById('fEst').value;
    filtered = rows.filter(r =>
        (!q||r.dataset.q.includes(q)) &&
        (!cat||r.dataset.cat===cat) &&
        (!est||r.dataset.est===est)
    );
    currentPage = 1;
    render();
}

function render(){
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    if (currentPage > totalPages) currentPage = totalPages;
    const start = (currentPage - 1) * PAGE_SIZE;
    const visible = new Set(filtered.slice(start, start + PAGE_SIZE));
    rows.forEach(r => { r.style.display = visible.has(r) ? '' : 'none'; });
    cnt.textContent = filtered.length;
    document.getElementById('pgInfo').textContent = `Página ${currentPage} de ${totalPages}`;
    document.getElementById('pgPrev').disabled = currentPage <= 1;
    document.getElementById('pgNext').disabled = currentPage >= totalPages;
}

function pagina(delta){
    currentPage += delta;
    render();
    document.getElementById('tbl').scrollIntoView({behavior:'smooth', block:'start'});
}

document.getElementById('q').addEventListener('input', filtrar);
document.getElementById('fCat').addEventListener('change', filtrar);
document.getElementById('fEst').addEventListener('change', filtrar);
filtrar();
