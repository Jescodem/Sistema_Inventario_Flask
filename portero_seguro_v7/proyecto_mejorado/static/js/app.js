/* app.js — comportamiento global de Portero Seguro:
   sidebar colapsable, inyección CSRF y estado de carga en formularios. */

    function _aplicarSidebar(colapsar){
        var sb = document.getElementById('sb');
        var mc = document.getElementById('mainContent');
        if(!sb || !mc) return;
        sb.classList.toggle('is-collapsed', colapsar);
        mc.classList.toggle('is-expanded', colapsar);
    }

    function toggleSidebar(){
        var sb = document.getElementById('sb');
        if(!sb) return;
        var colapsar = !sb.classList.contains('is-collapsed');
        _aplicarSidebar(colapsar);
        // Guarda la elección explícita del usuario: a partir de aquí su
        // preferencia manda sobre el auto-colapso por tamaño de pantalla.
        localStorage.setItem('sb_collapsed', colapsar ? '1' : '0');
    }

    // Estado inicial del sidebar:
    //  · Si el usuario ya eligió (colapsado/expandido), se respeta en cualquier ancho.
    //  · Si no hay preferencia guardada, se colapsa por defecto en pantallas angostas.
    (function(){
        var mq = window.matchMedia('(max-width:768px)');
        var guardado = localStorage.getItem('sb_collapsed');
        _aplicarSidebar(guardado !== null ? guardado === '1' : mq.matches);
        // Auto-ajuste al cruzar el breakpoint, solo mientras no haya preferencia manual.
        mq.addEventListener('change', function(e){
            if(localStorage.getItem('sb_collapsed') === null) _aplicarSidebar(e.matches);
        });
    })();
    // CSRF en todos los POST
    document.addEventListener('DOMContentLoaded',function(){
        var token=(document.querySelector('meta[name="csrf-token"]')||{}).content||'';
        document.querySelectorAll('form').forEach(function(form){
            if((form.getAttribute('method')||'').toUpperCase()!=='POST')return;
            if(form.querySelector('input[name="csrf_token"]'))return;
            var i=document.createElement('input');
            i.type='hidden';i.name='csrf_token';i.value=token;
            form.appendChild(i);
        });
    });

    // ── Estado de carga en formularios POST ────────────────────────────
    // Al enviar, deshabilita los botones de submit y muestra un spinner.
    // Previene el doble clic (guías/salidas duplicadas) y da feedback
    // visual en operaciones que tardan. Compatible con onsubmit=confirm():
    // si el usuario cancela, el evento submit nunca se dispara.
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('form[method="POST"], form[method="post"]').forEach(function (form) {
            form.addEventListener('submit', function () {
                if (form.dataset.enviado === '1') return;
                form.dataset.enviado = '1';
                form.querySelectorAll('button[type="submit"], button:not([type])').forEach(function (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' + btn.innerHTML;
                });
            });
        });
    });
