<?php

namespace App\Http\Controllers;

use App\Models\AuditLog;
use App\Models\ProcessAnalysis;
use App\Models\GeneratedDocument;
use App\Services\PlattEngineService;
use App\Services\StepUpService;
use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;

class ProcessoController extends Controller
{
    public function __construct(
        private PlattEngineService $engine,
        private StepUpService $stepUp
    ) {}

    /**
     * Analisa um processo do SEI.
     * 
     * POST /api/processos/analisar
     */
    public function analisar(Request $request): JsonResponse
    {
        $request->validate([
            'nup' => 'required|string|max:50',
            'opcoes' => 'array',
        ]);

        $user = $request->user();

        // Verifica se tem credencial
        if (!$user->hasCredencialSei()) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Você precisa vincular sua credencial SEI primeiro.',
                'acao_necessaria' => 'vincular_credencial',
            ], 400);
        }

        // Chama o Engine
        $resultado = $this->engine->analisarProcesso(
            user: $user,
            nup: $request->nup,
            opcoes: $request->opcoes ?? []
        );

        // Se sucesso, salva análise
        if ($resultado['sucesso'] ?? false) {
            $analise = ProcessAnalysis::create([
                'job_id' => $resultado['job_id'] ?? null,
                'user_id' => $user->id,
                'nup' => $request->nup,
                'resumo' => $resultado['analise']['resumo'] ?? null,
                'conclusao' => $resultado['analise']['conclusao'] ?? null,
                'interessado' => $resultado['analise']['interessado'] ?? null,
                'pedido' => $resultado['analise']['pedido'] ?? null,
                'legislacao' => $resultado['analise']['legislacao'] ?? null,
                'documentos' => $resultado['analise']['documentos'] ?? null,
                'alertas' => $resultado['analise']['alertas'] ?? null,
                'unidades' => $resultado['analise']['unidades'] ?? null,
                'texto_canonico' => $resultado['conteudo_bruto'] ?? null,
            ]);

            $resultado['analise_id'] = $analise->id;
        }

        return response()->json($resultado);
    }

    /**
     * Gera documento baseado na análise.
     * 
     * POST /api/processos/gerar-documento
     */
    public function gerarDocumento(Request $request): JsonResponse
    {
        $request->validate([
            'nup' => 'required|string|max:50',
            'tipo_documento' => 'required|string|max:50',
            'analise' => 'required|array',
            'destinatario' => 'nullable|string|max:100',
            'destinatarios' => 'nullable|array',
            'destinatarios.*.sigla' => 'required_with:destinatarios|string',
            'destinatarios.*.nome' => 'nullable|string',
            'destinatarios.*.posto_grad' => 'nullable|string',
            'destinatarios.*.cargo' => 'nullable|string',
            'remetente' => 'nullable|array',
            'template_id' => 'nullable|string|max:50',
        ]);

        $user = $request->user();

        $resultado = $this->engine->gerarDocumento(
            user: $user,
            nup: $request->nup,
            tipoDocumento: $request->tipo_documento,
            analise: $request->analise,
            destinatario: $request->destinatario,
            destinatarios: $request->destinatarios,
            remetente: $request->remetente,
            templateId: $request->template_id
        );

        // Se sucesso, salva documento gerado
        if ($resultado['sucesso'] ?? false) {
            $doc = GeneratedDocument::create([
                'user_id' => $user->id,
                'nup' => $request->nup,
                'tipo' => $request->tipo_documento,
                'destinatario' => $request->destinatario ?? ($request->destinatarios[0]['sigla'] ?? null),
                'conteudo_html' => $resultado['documento'] ?? '',
            ]);
            $resultado['documento_id'] = $doc->id;
        }

        return response()->json($resultado);
    }

    /**
     * Insere documento no SEI.
     * 
     * POST /api/processos/inserir-sei
     */
    public function inserirSei(Request $request): JsonResponse
    {
        $request->validate([
            'nup' => 'required|string|max:50',
            'tipo_documento' => 'required|string|max:50',
            'html' => 'required|string',
            'destinatario' => 'nullable|string|max:100',
        ]);

        $user = $request->user();

        if (!$user->hasCredencialSei()) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Credencial SEI não vinculada.',
            ], 400);
        }

        $resultado = $this->engine->inserirNoSei(
            user: $user,
            nup: $request->nup,
            tipoDocumento: $request->tipo_documento,
            html: $request->html,
            destinatario: $request->destinatario
        );

        return response()->json($resultado);
    }

    /**
     * Assina documento no SEI.
     * REQUER STEP-UP!
     * 
     * POST /api/processos/assinar
     */
    public function assinar(Request $request): JsonResponse
    {
        $request->validate([
            'sei_numero' => 'required|string|max:20',
        ]);

        $user = $request->user();

        // Verifica step-up
        if (!$this->stepUp->hasValidGrant($user, 'sign', $request->sei_numero, $request->ip())) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Autorização necessária.',
                'acao_necessaria' => 'step_up',
                'action' => 'sign',
                'target_id' => $request->sei_numero,
            ], 403);
        }

        if (!$user->hasCredencialSei()) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Credencial SEI não vinculada.',
            ], 400);
        }

        // Executa assinatura
        $resultado = $this->engine->assinarDocumento(
            user: $user,
            seiNumero: $request->sei_numero
        );

        // Consome o grant (uso único)
        $this->stepUp->consumeGrant($user, 'sign', $request->sei_numero);

        // Atualiza documento se existir
        if ($resultado['sucesso'] ?? false) {
            GeneratedDocument::where('sei_numero', $request->sei_numero)
                ->where('user_id', $user->id)
                ->update([
                    'assinado' => true,
                    'assinado_em' => now(),
                ]);
        }

        AuditLog::logSign($user->id, $request->sei_numero, $resultado['sucesso'] ?? false);

        return response()->json($resultado);
    }

    /**
     * Chat analítico sobre processo.
     * 
     * POST /api/processos/chat
     */
    public function chat(Request $request): JsonResponse
    {
        $request->validate([
            'mensagem' => 'required|string|max:5000',
            'texto_processo' => 'nullable|string',
            'modelo' => 'nullable|string|in:gpt-4o-mini,gpt-4o',
        ]);

        $user = $request->user();

        $resultado = $this->engine->chat(
            user: $user,
            mensagem: $request->mensagem,
            textoProcesso: $request->texto_processo,
            modelo: $request->modelo ?? 'gpt-4o-mini'
        );

        return response()->json($resultado);
    }

    /**
     * Consulta legislação (RAG).
     * 
     * POST /api/processos/consultar-lei
     */
    public function consultarLei(Request $request): JsonResponse
    {
        $request->validate([
            'consulta' => 'required|string|max:500',
            'n_results' => 'integer|min:1|max:20',
        ]);

        $resultado = $this->engine->consultarLegislacao(
            consulta: $request->consulta,
            nResults: $request->n_results ?? 5
        );

        return response()->json($resultado);
    }

    /**
     * Lista análises do usuário.
     * 
     * GET /api/processos/analises
     */
    public function listarAnalises(Request $request): JsonResponse
    {
        $user = $request->user();

        $analises = ProcessAnalysis::where('user_id', $user->id)
            ->orderBy('created_at', 'desc')
            ->limit($request->limit ?? 20)
            ->get([
                'id', 'nup', 'resumo', 'conclusao', 'created_at'
            ]);

        return response()->json([
            'analises' => $analises,
        ]);
    }

    /**
     * Obtém análise específica.
     * 
     * GET /api/processos/analises/{id}
     */
    public function obterAnalise(Request $request, int $id): JsonResponse
    {
        $user = $request->user();

        $analise = ProcessAnalysis::where('id', $id)
            ->where('user_id', $user->id)
            ->first();

        if (!$analise) {
            return response()->json([
                'erro' => 'Análise não encontrada.',
            ], 404);
        }

        return response()->json($analise);
    }

    /**
     * Lista documentos gerados pelo usuário.
     * 
     * GET /api/processos/documentos
     */
    public function listarDocumentos(Request $request): JsonResponse
    {
        $user = $request->user();

        $documentos = GeneratedDocument::where('user_id', $user->id)
            ->orderBy('created_at', 'desc')
            ->limit($request->limit ?? 20)
            ->get([
                'id', 'nup', 'tipo', 'destinatario', 
                'sei_numero', 'inserido_sei', 'assinado',
                'created_at'
            ]);

        return response()->json([
            'documentos' => $documentos,
        ]);
    }

    // ============================================================
    // ENVIAR E ATRIBUIR PROCESSO
    // ============================================================

    /**
     * Envia processo para outra unidade no SEI.
     * Fluxo em 3 estágios: search, preflight, commit.
     *
     * POST /api/processos/enviar
     */
    public function enviarProcesso(Request $request): JsonResponse
    {
        $request->validate([
            'nup' => 'required|string|max:50',
            'stage' => 'required|string|in:search,preflight,commit',
            'filtro' => 'nullable|string|max:100',
            'labels' => 'nullable|array',
            'labels.*' => 'string',
            'token' => 'nullable|string|max:255',
        ]);

        $user = $request->user();

        if (!$user->hasCredencialSei()) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Credencial SEI não vinculada.',
            ], 400);
        }

        $resultado = $this->engine->enviarProcesso(
            user: $user,
            nup: $request->nup,
            stage: $request->stage,
            filtro: $request->filtro,
            labels: $request->labels,
            token: $request->token
        );

        return response()->json($resultado);
    }

    /**
     * Atribui processo a um servidor no SEI.
     *
     * POST /api/processos/atribuir
     */
    public function atribuirProcesso(Request $request): JsonResponse
    {
        $request->validate([
            'nup' => 'required|string|max:50',
            'apelido' => 'required|string|max:100',
        ]);

        $user = $request->user();

        if (!$user->hasCredencialSei()) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Credencial SEI não vinculada.',
            ], 400);
        }

        $resultado = $this->engine->atribuirProcesso(
            user: $user,
            nup: $request->nup,
            apelido: $request->apelido
        );

        return response()->json($resultado);
    }

    // ============================================================
    // MÉTODOS ADICIONAIS PARA COMPATIBILIDADE COM FRONTEND v2.0
    // ============================================================

    /**
     * Valida documento antes de inserir.
     * 
     * POST /api/validar
     */
    public function validarDocumento(Request $request): JsonResponse
    {
        $request->validate([
            'texto' => 'required|string',
            'tipo' => 'required|string|max:50',
        ]);

        $texto = strip_tags($request->texto);
        $tipo = $request->tipo;
        $validacoes = [];

        // Verificar tamanho mínimo
        if (strlen($texto) < 50) {
            $validacoes[] = ['tipo' => 'warning', 'msg' => 'Documento muito curto (menos de 50 caracteres)'];
        } else {
            $validacoes[] = ['tipo' => 'ok', 'msg' => 'Tamanho adequado'];
        }

        // Verificar se tem saudação (para memorandos/ofícios)
        $tiposComSaudacao = ['Memorando', 'Ofício', 'Despacho'];
        if (in_array($tipo, $tiposComSaudacao)) {
            if (preg_match('/Senhor|Senhora|Prezado|Exmo|Ilmo/i', $texto)) {
                $validacoes[] = ['tipo' => 'ok', 'msg' => 'Saudação identificada'];
            } else {
                $validacoes[] = ['tipo' => 'warning', 'msg' => 'Considere adicionar saudação formal'];
            }
        }

        // Verificar se tem fechamento
        if (preg_match('/Atenciosamente|Respeitosamente|Cordialmente/i', $texto)) {
            $validacoes[] = ['tipo' => 'ok', 'msg' => 'Fechamento identificado'];
        } else {
            $validacoes[] = ['tipo' => 'warning', 'msg' => 'Considere adicionar fechamento formal'];
        }

        // Verificar referência ao processo
        if (preg_match('/\d{4}\.\d{6}\.\d{5}\/\d{4}-\d{2}/', $texto)) {
            $validacoes[] = ['tipo' => 'ok', 'msg' => 'Referência ao processo (NUP) encontrada'];
        }

        return response()->json([
            'sucesso' => true,
            'validacoes' => $validacoes,
        ]);
    }

    /**
     * Melhora texto usando IA.
     * 
     * POST /api/melhorar-texto
     */
    public function melhorarTexto(Request $request): JsonResponse
    {
        $request->validate([
            'texto' => 'required|string',
        ]);

        $user = $request->user();
        
        $resultado = $this->engine->melhorarTexto(
            user: $user,
            texto: $request->texto
        );

        return response()->json($resultado);
    }

    /**
     * Upload de arquivo para anexar ao chat.
     * 
     * POST /api/upload-arquivo
     */
    public function uploadArquivo(Request $request): JsonResponse
    {
        $request->validate([
            'arquivo' => 'required|file|max:10240|mimes:pdf,doc,docx,txt,html',
            'origem' => 'string|max:50',
        ]);

        $user = $request->user();
        $file = $request->file('arquivo');
        
        // Extrair texto do arquivo
        $texto = '';
        $extension = strtolower($file->getClientOriginalExtension());
        
        if ($extension === 'txt' || $extension === 'html') {
            $texto = file_get_contents($file->getRealPath());
        } elseif ($extension === 'pdf') {
            // Tentar extrair texto do PDF
            try {
                $parser = new \Smalot\PdfParser\Parser();
                $pdf = $parser->parseFile($file->getRealPath());
                $texto = $pdf->getText();
            } catch (\Exception $e) {
                $texto = '[Não foi possível extrair texto do PDF]';
            }
        } else {
            $texto = '[Formato não suportado para extração de texto]';
        }

        // Salvar arquivo temporariamente
        $path = $file->store('uploads/chat', 'local');

        return response()->json([
            'sucesso' => true,
            'arquivo' => [
                'nome' => $file->getClientOriginalName(),
                'tipo' => $extension,
                'tamanho' => $file->getSize(),
                'origem' => $request->origem ?? 'DOCUMENTO_EXTERNO',
                'path' => $path,
            ],
            'texto_completo' => substr($texto, 0, 50000), // Limitar a 50k chars
        ]);
    }

    /**
     * Lista autoridades/efetivo do CBMAC.
     * 
     * GET /api/autoridades
     */
    public function listarAutoridades(Request $request): JsonResponse
    {
        // Buscar do FastAPI (que tem o banco de autoridades)
        try {
            $response = \Illuminate\Support\Facades\Http::timeout(10)
                ->get(config('services.platt_engine.url') . '/api/autoridades');
            
            if ($response->successful()) {
                return response()->json($response->json());
            }
            
            return response()->json([
                'autoridades' => [],
                'erro' => 'Não foi possível carregar autoridades'
            ]);
        } catch (\Exception $e) {
            return response()->json([
                'autoridades' => [],
                'erro' => $e->getMessage()
            ]);
        }
    }

    // ============================================================
    // BLOCOS DE ASSINATURA
    // ============================================================

    /**
     * Lista documentos de um bloco de assinatura.
     * 
     * GET /api/blocos/{blocoId}
     */
    public function listarBloco(Request $request, string $blocoId): JsonResponse
    {
        $user = $request->user();

        if (!$user->hasCredencialSei()) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Credencial SEI não vinculada.',
            ], 400);
        }

        $resultado = $this->engine->listarDocsBloco($user, $blocoId);

        return response()->json($resultado);
    }

    /**
     * Visualiza documento para preview.
     * 
     * POST /api/documento/visualizar
     */
    public function visualizarDocumento(Request $request): JsonResponse
    {
        $request->validate([
            'documento_id' => 'required|string|max:20',
        ]);

        $user = $request->user();

        if (!$user->hasCredencialSei()) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Credencial SEI não vinculada.',
            ], 400);
        }

        $resultado = $this->engine->visualizarDocumento($user, $request->documento_id);

        return response()->json($resultado);
    }

    /**
     * Assina um documento específico do bloco.
     * 
     * POST /api/documento/assinar
     */
    public function assinarDocumentoBloco(Request $request): JsonResponse
    {
        $request->validate([
            'documento_id' => 'required|string|max:20',
        ]);

        $user = $request->user();

        if (!$user->hasCredencialSei()) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Credencial SEI não vinculada.',
            ], 400);
        }

        $resultado = $this->engine->assinarDocumentoBloco($user, $request->documento_id);

        AuditLog::create([
            'user_id' => $user->id,
            'action' => 'assinar_documento_bloco',
            'target_type' => 'documento',
            'target_id' => $request->documento_id,
            'status' => ($resultado['sucesso'] ?? false) ? 'success' : 'failure',
        ]);

        return response()->json($resultado);
    }

    /**
     * Assina todos os documentos de um bloco.
     * 
     * POST /api/bloco/assinar
     */
    public function assinarBlocoCompleto(Request $request): JsonResponse
    {
        $request->validate([
            'bloco_id' => 'required|string|max:20',
        ]);

        $user = $request->user();

        if (!$user->hasCredencialSei()) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Credencial SEI não vinculada.',
            ], 400);
        }

        $resultado = $this->engine->assinarBloco($user, $request->bloco_id);

        AuditLog::create([
            'user_id' => $user->id,
            'action' => 'assinar_bloco',
            'target_type' => 'bloco',
            'target_id' => $request->bloco_id,
            'status' => ($resultado['sucesso'] ?? false) ? 'success' : 'failure',
        ]);

        return response()->json($resultado);
    }
}
