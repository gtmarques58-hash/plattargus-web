Implemente o painel de entrada de voz/texto no arquivo analisar.html seguindo estas instruções:

## O QUE FAZER:
Adicionar um painel com entrada de voz e texto que aparece após analisar um processo, permitindo ao usuário dar comandos como "memorando coc", "deferir pedido", etc.

## ONDE ADICIONAR:

### 1. CSS - Adicione ANTES de </style> (após linha 188):

```css
/* ===== PAINEL DE VOZ v1.0 ===== */
.voice-command-section{background:linear-gradient(135deg,rgba(230,57,70,0.1),rgba(245,158,11,0.1));border:2px dashed var(--warning);border-radius:12px;padding:16px;margin-bottom:15px}
.voice-command-label{display:flex;align-items:center;gap:8px;font-size:0.9rem;font-weight:600;color:var(--warning);margin-bottom:12px}
.new-badge{background:var(--accent);color:white;font-size:0.65rem;padding:2px 6px;border-radius:4px;font-weight:700}
.voice-input-wrapper{display:flex;gap:10px;align-items:flex-start}
.voice-text-input{flex:1;padding:14px 16px;border-radius:10px;border:1px solid var(--border-color);background:var(--bg-primary);color:var(--text-primary);font-size:0.95rem;font-family:var(--font-display);resize:none;min-height:80px}
.voice-text-input:focus{outline:none;border-color:var(--warning);box-shadow:0 0 0 3px rgba(245,158,11,0.2)}
.voice-text-input::placeholder{color:var(--text-muted)}
.voice-btn-container{display:flex;flex-direction:column;gap:8px}
.voice-btn{width:56px;height:56px;border-radius:50%;border:none;background:linear-gradient(135deg,var(--accent),#b91c1c);color:white;font-size:24px;cursor:pointer;transition:all 0.3s;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 15px var(--accent-glow)}
.voice-btn:hover{transform:scale(1.1);box-shadow:0 6px 20px var(--accent-glow)}
.voice-btn.listening{animation:voicePulse 1.5s infinite;background:var(--success);box-shadow:0 4px 15px rgba(16,185,129,0.6)}
@keyframes voicePulse{0%,100%{transform:scale(1)}50%{transform:scale(1.15)}}
.voice-send-btn{width:56px;height:36px;border-radius:8px;border:none;background:var(--success);color:white;font-size:18px;cursor:pointer;transition:all 0.2s}
.voice-send-btn:hover{background:#0ea66d}
.voice-examples{margin-top:12px;padding-top:12px;border-top:1px solid var(--border-color)}
.voice-examples-title{font-size:0.75rem;color:var(--text-muted);margin-bottom:8px}
.quick-commands{display:flex;flex-wrap:wrap;gap:6px}
.quick-cmd{padding:6px 12px;border-radius:6px;border:1px solid var(--border-color);background:var(--bg-primary);color:var(--text-muted);font-size:0.8rem;cursor:pointer;transition:all 0.2s;font-family:var(--font-display)}
.quick-cmd:hover{border-color:var(--warning);color:var(--warning);background:rgba(245,158,11,0.1)}
.voice-overlay{position:fixed;inset:0;background:rgba(10,14,20,0.95);display:none;align-items:center;justify-content:center;flex-direction:column;z-index:2000}
.voice-overlay.active{display:flex}
.voice-circle{width:150px;height:150px;border-radius:50%;background:linear-gradient(135deg,var(--accent),#b91c1c);display:flex;align-items:center;justify-content:center;font-size:60px;animation:voicePulse 1.5s infinite;box-shadow:0 0 60px var(--accent-glow)}
.voice-listening-text{margin-top:24px;font-size:1.2rem;color:var(--text-primary)}
.voice-transcript{margin-top:16px;padding:16px 32px;background:var(--bg-card);border-radius:12px;font-size:1rem;max-width:500px;text-align:center;min-height:50px;color:var(--text-secondary);border:1px solid var(--border-color)}
.voice-cancel-btn{margin-top:24px;padding:12px 32px;border-radius:8px;border:1px solid var(--border-color);background:transparent;color:var(--text-primary);cursor:pointer;font-family:var(--font-display);transition:all 0.2s}
.voice-cancel-btn:hover{border-color:var(--accent);color:var(--accent)}
```

### 2. HTML - Adicione ANTES de `<div id="configBox"` (linha ~257):

```html
<!-- ===== PAINEL DE VOZ v1.0 ===== -->
<div id="voiceCommandSection" class="voice-command-section hidden">
    <div class="voice-command-label">🎙️ Comando por Voz ou Texto <span class="new-badge">v1.0</span></div>
    <div class="voice-input-wrapper">
        <textarea id="voiceInput" class="voice-text-input" placeholder="Fale ou digite seu comando...&#10;&#10;Ex: &quot;memorando para COC informando que o pedido foi deferido&quot;&#10;Ex: &quot;despacho para DLPF encaminhando para providências&quot;"></textarea>
        <div class="voice-btn-container">
            <button class="voice-btn" id="voiceBtn" onclick="toggleVoiceListening()" title="Clique para falar">🎤</button>
            <button class="voice-send-btn" onclick="processVoiceCommand()" title="Enviar comando">➤</button>
        </div>
    </div>
    <div class="voice-examples">
        <div class="voice-examples-title">Comandos rápidos:</div>
        <div class="quick-commands">
            <button class="quick-cmd" onclick="setQuickCommand('memorando coc')">Memo COC</button>
            <button class="quick-cmd" onclick="setQuickCommand('memorando coi')">Memo COI</button>
            <button class="quick-cmd" onclick="setQuickCommand('memorando cmdger')">Memo CMDGER</button>
            <button class="quick-cmd" onclick="setQuickCommand('memorando subcmd')">Memo SUBCMD</button>
            <button class="quick-cmd" onclick="setQuickCommand('deferir pedido')">Deferir</button>
            <button class="quick-cmd" onclick="setQuickCommand('indeferir pedido')">Indeferir</button>
            <button class="quick-cmd" onclick="setQuickCommand('voltar processo')">Voltar</button>
        </div>
    </div>
</div>
```

### 3. HTML - Adicione ANTES de </body> (overlay de voz):

```html
<div id="voiceOverlay" class="voice-overlay">
    <div class="voice-circle">🎤</div>
    <div class="voice-listening-text">Ouvindo...</div>
    <div id="voiceTranscript" class="voice-transcript">Fale seu comando...</div>
    <button class="voice-cancel-btn" onclick="toggleVoiceListening()">Cancelar</button>
</div>
```

### 4. JavaScript - Adicione após as variáveis globais (~linha 637):

```javascript
// ========== PAINEL DE VOZ v1.0 ==========
var isVoiceListening = false;
var voiceRecognition = null;
var unidadesMap = {
    'coc': { sigla: 'COC', nome: 'Comando Operacional da Capital' },
    'coi': { sigla: 'COI', nome: 'Comando Operacional do Interior' },
    'cmdger': { sigla: 'CMDGER', nome: 'Comando Geral' },
    'subcmd': { sigla: 'SUBCMD', nome: 'Subcomando Geral' },
    'drh': { sigla: 'DRH', nome: 'Diretoria de Recursos Humanos' },
    'dlpf': { sigla: 'DLPF', nome: 'Diretoria de Logística, Finanças e Patrimônio' },
    'dei': { sigla: 'DEI', nome: 'Diretoria de Ensino e Instrução' },
    'ajger': { sigla: 'AJGER', nome: 'Ajudância Geral' },
    'assjur': { sigla: 'ASSJUR', nome: 'Assessoria Jurídica' }
};
var comandosMap = {
    'memorando': { tipo: 'Memorando', template: 'MEMO_GENERICO' },
    'memo': { tipo: 'Memorando', template: 'MEMO_GENERICO' },
    'despacho': { tipo: 'Despacho', template: 'DESPACHO_SIMPLES' },
    'deferir': { tipo: 'Despacho', template: 'DESPACHO_DEFERIMENTO' },
    'indeferir': { tipo: 'Despacho', template: 'DESPACHO_INDEFERIMENTO' },
    'voltar': { tipo: 'Despacho', template: 'DESPACHO_ENCAMINHAMENTO' }
};

function initVoiceRecognition() {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) return;
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    voiceRecognition = new SpeechRecognition();
    voiceRecognition.continuous = false;
    voiceRecognition.interimResults = true;
    voiceRecognition.lang = 'pt-BR';
    voiceRecognition.onresult = function(event) {
        var transcript = '';
        for (var i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
        }
        document.getElementById('voiceTranscript').textContent = '"' + transcript + '"';
        if (event.results[event.results.length - 1].isFinal) {
            document.getElementById('voiceInput').value = transcript;
            setTimeout(function() { toggleVoiceListening(); processVoiceCommand(); }, 500);
        }
    };
    voiceRecognition.onerror = function(event) {
        document.getElementById('voiceTranscript').textContent = 'Erro: ' + event.error;
        setTimeout(function() { toggleVoiceListening(); }, 2000);
    };
}

function toggleVoiceListening() {
    isVoiceListening = !isVoiceListening;
    var overlay = document.getElementById('voiceOverlay');
    var btn = document.getElementById('voiceBtn');
    if (isVoiceListening) {
        overlay.classList.add('active');
        btn.classList.add('listening');
        document.getElementById('voiceTranscript').textContent = 'Fale seu comando...';
        if (!voiceRecognition) initVoiceRecognition();
        if (voiceRecognition) try { voiceRecognition.start(); } catch (e) {}
    } else {
        overlay.classList.remove('active');
        btn.classList.remove('listening');
        if (voiceRecognition) try { voiceRecognition.stop(); } catch (e) {}
    }
}

function setQuickCommand(cmd) {
    document.getElementById('voiceInput').value = cmd;
    processVoiceCommand();
}

function processVoiceCommand() {
    var input = document.getElementById('voiceInput').value.trim().toLowerCase();
    if (!input) return;
    var tipoDetectado = null, templateDetectado = 'DESPACHO_SIMPLES', destDetectado = null;
    Object.keys(comandosMap).forEach(function(key) {
        if (input.indexOf(key) >= 0) { tipoDetectado = comandosMap[key].tipo; templateDetectado = comandosMap[key].template; }
    });
    Object.keys(unidadesMap).forEach(function(key) {
        if (input.indexOf(key) >= 0) { destDetectado = unidadesMap[key]; }
    });
    if (tipoDetectado) {
        document.getElementById('tipoDocumento').value = tipoDetectado;
        document.getElementById('tipoDocumentoInput').value = tipoDetectado;
        window.templateSelecionado = templateDetectado;
    }
    if (destDetectado) {
        destinatariosSelecionados = [];
        document.querySelectorAll('.tag-item').forEach(function(el) { el.remove(); });
        var autoridade = todasAutoridades.find(function(a) { return (a.sigla || '').toUpperCase() === destDetectado.sigla; });
        if (autoridade) {
            destinatariosSelecionados.push({ sigla: autoridade.sigla, nome: autoridade.nome || destDetectado.nome });
            var tagsContainer = document.getElementById('tagsContainer');
            var tagInput = document.getElementById('destinatarioInput');
            var tagEl = document.createElement('span');
            tagEl.className = 'tag-item';
            tagEl.innerHTML = autoridade.sigla + ' <button class="tag-remove" onclick="removerDestinatario(this, \'' + autoridade.sigla + '\')">×</button>';
            tagsContainer.insertBefore(tagEl, tagInput);
        }
    }
    window.instrucaoVoz = input;
    if (tipoDetectado || destDetectado) setTimeout(function() { gerarDocumento(); }, 300);
}

window.addEventListener('load', function() { initVoiceRecognition(); });
```

### 5. Modificar função lerProcesso() (~linha 967):

Adicione 'voiceCommandSection' na lista de elementos a esconder:
```javascript
['resumoBox', 'infoGrid', 'alertasBox', 'docsProcessoBox', 'sugestaoBox', 'configBox', 'editorContainer', 'validacoesBox', 'chatSection', 'acoesProcessoBox', 'voiceCommandSection'].forEach(...)
```

### 6. Modificar função lerProcesso() (~linha 1011):

Após `document.getElementById('configBox').classList.remove('hidden');` adicione:
```javascript
document.getElementById('voiceCommandSection').classList.remove('hidden');
```

## RESULTADO ESPERADO:
- Após analisar um processo, aparece o painel de voz com botões rápidos
- Usuário pode falar ou digitar comandos como "memorando coc"
- Sistema detecta tipo de documento e destinatário automaticamente
- Gera o documento chamando a função existente gerarDocumento()
