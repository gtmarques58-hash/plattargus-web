<?php

namespace App\Services;

use App\Models\User;
use App\Models\AuditLog;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Str;

/**
 * PlattEngineService - Comunicação com FastAPI Engine
 * 
 * Gerencia todas as chamadas ao motor de execução (SEI, OCR, RAG, IA).
 * Implementa segurança HMAC para comunicação interna.
 */
class PlattEngineService
{
    private string $baseUrl;
    private string $runnerUrl;
    private string $secret;
    private int $timeout;
    private CredentialVaultService $vault;

    public function __construct(CredentialVaultService $vault)
    {
        $this->baseUrl = rtrim(config('services.platt_engine.url'), '/');
        $this->runnerUrl = rtrim(config('services.platt_engine.runner_url', 'http://localhost:8001'), '/');
        $this->secret = config('services.platt_engine.secret');
        $this->timeout = (int) config('services.platt_engine.timeout', 120);
        $this->vault = $vault;

        if (empty($this->secret)) {
            throw new \RuntimeException('PLATT_ENGINE_SECRET não configurado');
        }
    }

    // =========================================================================
    // ANÁLISE DE PROCESSO
    // =========================================================================

    /**
     * Analisa um processo do SEI.
     * 
     * @param User $user Usuário solicitante
     * @param string $nup NUP do processo
     * @param array $opcoes Opções adicionais
     * @return array Resultado da análise
     */
    public function analisarProcesso(User $user, string $nup, array $opcoes = []): array
    {
        $credencial = $user->getCredencialSei();
        
        if (!$credencial) {
            return [
                'sucesso' => false,
                'erro' => 'Usuário não possui credencial SEI cadastrada',
            ];
        }

        // Formato esperado pelo FastAPI /api/v2/analisar-processo
        $payload = [
            'nup' => $nup,
            'credencial' => [
                'usuario' => $credencial['usuario'],
                'senha' => $credencial['senha'],
                'orgao_id' => $credencial['orgao_id'] ?? '31',
            ],
        ];

        // Limpa senha da memória após criar payload
        $credencial['senha'] = str_repeat("\0", strlen($credencial['senha']));
        unset($credencial);

        $response = $this->post('/api/v2/analisar-processo', $payload);

        $this->logAction($user, 'analisar_processo', $nup, $response);

        return $response;
    }

    // =========================================================================
    // GERAÇÃO DE DOCUMENTO
    // =========================================================================

    /**
     * Gera um documento baseado na análise.
     * 
     * @param User $user
     * @param string $nup
     * @param string $tipoDocumento
     * @param array $analise
     * @param string|null $destinatario
     * @return array
     */
    public function gerarDocumento(
        User $user, 
        string $nup, 
        string $tipoDocumento, 
        array $analise,
        ?string $destinatario = null,
        ?array $destinatarios = null,
        ?array $remetente = null,
        ?string $templateId = null
    ): array {
        $payload = [
            'job_id' => 'job_' . Str::ulid(),
            'user_id' => $user->id,
            'nup' => $nup,
            'modo' => 'gerar',
            'tipo_documento' => $tipoDocumento,
            'template_id' => $templateId,
            'analise' => $analise,
            'destinatario' => $destinatario,
            'destinatarios' => $destinatarios,
            'remetente' => $remetente ?? [
                'nome' => $user->nome_completo,
                'posto_grad' => $user->posto_grad,
                'cargo' => $user->cargo,
                'unidade' => $user->unidade,
            ],
            'usuario_sei' => $user->usuario_sei,
        ];

        $response = $this->post('/v1/gerar-documento', $payload);

        $this->logAction($user, 'gerar_documento', $nup, $response, [
            'tipo' => $tipoDocumento,
        ]);

        return $response;
    }

    // =========================================================================
    // ASSINATURA DE DOCUMENTO
    // =========================================================================

    /**
     * Assina um documento no SEI.
     * REQUER step-up prévio!
     * 
     * @param User $user
     * @param string $seiNumero Número SEI do documento
     * @return array
     */
    public function assinarDocumento(User $user, string $seiNumero): array
    {
        $credencial = $user->getCredencialSei();
        
        if (!$credencial) {
            return [
                'sucesso' => false,
                'erro' => 'Usuário não possui credencial SEI cadastrada',
            ];
        }

        $payload = [
            'job_id' => 'job_' . Str::ulid(),
            'user_id' => $user->id,
            'modo' => 'assinar',
            'sei_numero' => $seiNumero,
            'credencial' => [
                'usuario' => $credencial['usuario'],
                'senha' => $credencial['senha'],
                'orgao_id' => $credencial['orgao_id'],
                'cargo' => $credencial['cargo'],
            ],
        ];

        // Limpa senha da memória
        $credencial['senha'] = str_repeat("\0", strlen($credencial['senha']));
        unset($credencial);

        $response = $this->post('/v1/assinar', $payload);

        $this->logAction($user, 'assinar_documento', $seiNumero, $response);

        return $response;
    }

    // =========================================================================
    // CHAT ANALÍTICO
    // =========================================================================

    /**
     * Envia mensagem para o chat analítico.
     * 
     * @param User $user
     * @param string $mensagem
     * @param string|null $textoProcesso Contexto do processo
     * @param string|null $modelo Modelo de IA
     * @return array
     */
    public function chat(
        User $user, 
        string $mensagem, 
        ?string $textoProcesso = null,
        ?string $modelo = 'gpt-4o-mini'
    ): array {
        $payload = [
            'user_id' => $user->id,
            'usuario_sei' => $user->usuario_sei,
            'mensagem' => $mensagem,
            'texto_canonico' => $textoProcesso ?? '',
            'modelo_forcado' => $modelo,
            'acao' => 'CHAT_LIVRE',
        ];

        return $this->post('/api/chat', $payload);
    }

    // =========================================================================
    // CONSULTA DE LEGISLAÇÃO (RAG)
    // =========================================================================

    /**
     * Consulta legislação no ChromaDB.
     * 
     * @param string $consulta
     * @param int $nResults
     * @return array
     */
    public function consultarLegislacao(string $consulta, int $nResults = 5): array
    {
        $payload = [
            'consulta' => $consulta,
            'n_results' => $nResults,
        ];

        return $this->post('/api/consultar-lei', $payload);
    }

    // =========================================================================
    // INSERÇÃO NO SEI
    // =========================================================================

    /**
     * Insere documento no SEI.
     * 
     * @param User $user
     * @param string $nup
     * @param string $tipoDocumento
     * @param string $html Conteúdo HTML do documento
     * @param string|null $destinatario
     * @return array
     */
    public function inserirNoSei(
        User $user, 
        string $nup, 
        string $tipoDocumento, 
        string $html,
        ?string $destinatario = null
    ): array {
        $credencial = $user->getCredencialSei();
        
        if (!$credencial) {
            return [
                'sucesso' => false,
                'erro' => 'Usuário não possui credencial SEI cadastrada',
            ];
        }

        $payload = [
            'job_id' => 'job_' . Str::ulid(),
            'user_id' => $user->id,
            'nup' => $nup,
            'tipo_documento' => $tipoDocumento,
            'html' => $html,
            'destinatario' => $destinatario,
            'credencial' => [
                'usuario' => $credencial['usuario'],
                'senha' => $credencial['senha'],
                'orgao_id' => $credencial['orgao_id'],
            ],
        ];

        // Limpa senha da memória
        $credencial['senha'] = str_repeat("\0", strlen($credencial['senha']));
        unset($credencial);

        $response = $this->post('/v1/inserir-sei', $payload);

        $this->logAction($user, 'inserir_sei', $nup, $response, [
            'tipo' => $tipoDocumento,
        ]);

        return $response;
    }

    // =========================================================================
    // HEALTH CHECK
    // =========================================================================

    /**
     * Verifica se o Engine está online.
     * 
     * @return array
     */
    public function healthCheck(): array
    {
        try {
            $response = Http::timeout(5)->get($this->baseUrl . '/');
            
            return [
                'online' => $response->successful(),
                'status' => $response->status(),
                'data' => $response->json(),
            ];
        } catch (\Exception $e) {
            return [
                'online' => false,
                'error' => $e->getMessage(),
            ];
        }
    }

    // =========================================================================
    // HTTP COM HMAC
    // =========================================================================

    /**
     * Faz requisição POST com assinatura HMAC.
     */
    private function post(string $path, array $payload): array
    {
        $url = $this->baseUrl . $path;
        $body = json_encode($payload);
        $headers = $this->buildHmacHeaders('POST', $path, $body);

        try {
            $response = Http::withHeaders($headers)
                ->timeout($this->timeout)
                ->withBody($body, 'application/json')
                ->post($url);

            if ($response->successful()) {
                return array_merge(['sucesso' => true], $response->json() ?? []);
            }

            Log::error('PlattEngine error', [
                'url' => $url,
                'status' => $response->status(),
                'body' => $response->body(),
            ]);

            return [
                'sucesso' => false,
                'erro' => 'Erro do Engine: ' . $response->status(),
                'detalhes' => $response->json() ?? $response->body(),
            ];

        } catch (\Exception $e) {
            Log::error('PlattEngine exception', [
                'url' => $url,
                'error' => $e->getMessage(),
            ]);

            return [
                'sucesso' => false,
                'erro' => 'Falha na comunicação com Engine: ' . $e->getMessage(),
            ];
        }
    }

    /**
     * Faz requisição POST ao Runner (Playwright scripts).
     */
    private function postRunner(array $payload): array
    {
        $url = $this->runnerUrl . '/run';
        $body = json_encode($payload);

        try {
            $response = Http::timeout($this->timeout)
                ->withBody($body, 'application/json')
                ->post($url);

            if ($response->successful()) {
                $data = $response->json() ?? [];
                return array_merge(['sucesso' => $data['ok'] ?? false], $data);
            }

            Log::error('PlattRunner error', [
                'url' => $url,
                'status' => $response->status(),
                'body' => $response->body(),
            ]);

            return [
                'sucesso' => false,
                'erro' => 'Erro do Runner: ' . $response->status(),
                'detalhes' => $response->json() ?? $response->body(),
            ];

        } catch (\Exception $e) {
            Log::error('PlattRunner exception', [
                'url' => $url,
                'error' => $e->getMessage(),
            ]);

            return [
                'sucesso' => false,
                'erro' => 'Falha na comunicação com Runner: ' . $e->getMessage(),
            ];
        }
    }

    /**
     * Constrói headers HMAC para autenticação.
     * 
     * Formato da assinatura:
     * base = timestamp + "\n" + METHOD + "\n" + path + "\n" + SHA256(body)
     * signature = HMAC-SHA256(secret, base)
     */
    private function buildHmacHeaders(string $method, string $path, string $body): array
    {
        $timestamp = time();
        $requestId = Str::uuid()->toString();
        $bodyHash = hash('sha256', $body);
        
        $base = $timestamp . "\n" . strtoupper($method) . "\n" . $path . "\n" . $bodyHash;
        $signature = hash_hmac('sha256', $base, $this->secret);

        return [
            'Content-Type' => 'application/json',
            'X-Timestamp' => (string) $timestamp,
            'X-Request-ID' => $requestId,
            'X-Signature' => $signature,
        ];
    }

    /**
     * Registra ação no log de auditoria.
     */
    private function logAction(
        User $user, 
        string $action, 
        string $targetId, 
        array $response,
        array $extra = []
    ): void {
        AuditLog::create([
            'user_id' => $user->id,
            'action' => $action,
            'target_type' => 'sei',
            'target_id' => $targetId,
            'status' => ($response['sucesso'] ?? false) ? 'success' : 'failure',
            'metadata' => array_merge([
                'response_sucesso' => $response['sucesso'] ?? false,
                'response_erro' => $response['erro'] ?? null,
            ], $extra),
        ]);
    }

    /**
     * Melhora texto usando IA.
     */
    public function melhorarTexto(User $user, string $texto): array
    {
        $payload = [
            'texto' => $texto,
            'usuario_sei' => $user->usuario_sei,
            'acao' => 'melhorar',
        ];

        try {
            $response = $this->post('/api/melhorar-texto', $payload);
            
            $this->logAction($user, 'melhorar_texto', 'texto', $response, [
                'tamanho_original' => strlen($texto),
            ]);
            
            return $response;
        } catch (\Exception $e) {
            return [
                'sucesso' => false,
                'erro' => 'Erro ao melhorar texto: ' . $e->getMessage(),
            ];
        }
    }

    // =========================================================================
    // ENVIAR PROCESSO
    // =========================================================================

    /**
     * Envia processo para outra unidade no SEI.
     * Fluxo em 3 estágios: search → preflight → commit.
     *
     * @param User $user
     * @param string $nup
     * @param string $stage Estágio: "search", "preflight" ou "commit"
     * @param string|null $filtro Filtro para buscar unidades (usado no search)
     * @param array|null $labels Labels selecionados (usado no preflight/commit)
     * @param string|null $token Token retornado pelo preflight (usado no commit)
     * @return array
     */
    public function enviarProcesso(
        User $user,
        string $nup,
        string $stage,
        ?string $filtro = null,
        ?array $labels = null,
        ?string $token = null
    ): array {
        $credencial = $user->getCredencialSei();

        if (!$credencial) {
            return [
                'sucesso' => false,
                'erro' => 'Usuário não possui credencial SEI cadastrada',
            ];
        }

        $payload = [
            'mode' => 'enviar',
            'nup' => $nup,
            'stage' => $stage,
            'credentials' => [
                'usuario' => $credencial['usuario'],
                'senha' => $credencial['senha'],
                'orgao_id' => $credencial['orgao_id'] ?? '31',
            ],
        ];

        if ($filtro) {
            $payload['filtro'] = $filtro;
        }

        if ($labels) {
            $payload['labels'] = $labels;
        }

        if ($token) {
            $payload['token'] = $token;
        }

        // Limpa senha da memória
        $credencial['senha'] = str_repeat("\0", strlen($credencial['senha']));
        unset($credencial);

        $response = $this->postRunner($payload);

        $this->logAction($user, 'enviar_processo', $nup, $response, [
            'stage' => $stage,
        ]);

        return $response;
    }

    // =========================================================================
    // ATRIBUIR PROCESSO
    // =========================================================================

    /**
     * Atribui processo a um servidor no SEI.
     *
     * @param User $user
     * @param string $nup
     * @param string $apelido Login/apelido do servidor destino
     * @return array
     */
    public function atribuirProcesso(User $user, string $nup, string $apelido): array
    {
        $credencial = $user->getCredencialSei();

        if (!$credencial) {
            return [
                'sucesso' => false,
                'erro' => 'Usuário não possui credencial SEI cadastrada',
            ];
        }

        $payload = [
            'mode' => 'atribuir',
            'nup' => $nup,
            'apelido' => $apelido,
            'credentials' => [
                'usuario' => $credencial['usuario'],
                'senha' => $credencial['senha'],
                'orgao_id' => $credencial['orgao_id'] ?? '31',
            ],
        ];

        // Limpa senha da memória
        $credencial['senha'] = str_repeat("\0", strlen($credencial['senha']));
        unset($credencial);

        $response = $this->postRunner($payload);

        $this->logAction($user, 'atribuir_processo', $nup, $response, [
            'apelido' => $apelido,
        ]);

        return $response;
    }

    // =========================================================================
    // BLOCOS DE ASSINATURA
    // =========================================================================

    /**
     * Lista documentos de um bloco de assinatura.
     * 
     * @param User $user
     * @param string $blocoId
     * @return array
     */
    public function listarDocsBloco(User $user, string $blocoId): array
    {
        $credencial = $user->getCredencialSei();

        if (!$credencial) {
            return [
                'sucesso' => false,
                'erro' => 'Usuário não possui credencial SEI cadastrada',
            ];
        }

        $payload = [
            'usuario_sei' => $credencial['usuario'],
            'bloco_id' => $blocoId,
            'credenciais' => [
                'usuario' => $credencial['usuario'],
                'senha' => $credencial['senha'],
                'orgao_id' => $credencial['orgao_id'] ?? '31',
            ],
        ];

        $credencial['senha'] = str_repeat("\0", strlen($credencial['senha']));
        unset($credencial);

        return $this->post('/api/blocos/listar', $payload);
    }

    /**
     * Visualiza documento para preview.
     * 
     * @param User $user
     * @param string $documentoId
     * @return array
     */
    public function visualizarDocumento(User $user, string $documentoId): array
    {
        $credencial = $user->getCredencialSei();

        if (!$credencial) {
            return [
                'sucesso' => false,
                'erro' => 'Usuário não possui credencial SEI cadastrada',
            ];
        }

        $payload = [
            'usuario_sei' => $credencial['usuario'],
            'documento_id' => $documentoId,
            'credenciais' => [
                'usuario' => $credencial['usuario'],
                'senha' => $credencial['senha'],
                'orgao_id' => $credencial['orgao_id'] ?? '31',
            ],
        ];

        $credencial['senha'] = str_repeat("\0", strlen($credencial['senha']));
        unset($credencial);

        $response = $this->post('/api/documento/visualizar', $payload);

        $this->logAction($user, 'visualizar_documento', $documentoId, $response);

        return $response;
    }

    /**
     * Assina um documento específico do bloco.
     * 
     * @param User $user
     * @param string $documentoId
     * @return array
     */
    public function assinarDocumentoBloco(User $user, string $documentoId): array
    {
        $credencial = $user->getCredencialSei();

        if (!$credencial) {
            return [
                'sucesso' => false,
                'erro' => 'Usuário não possui credencial SEI cadastrada',
            ];
        }

        $payload = [
            'usuario_sei' => $credencial['usuario'],
            'documento_id' => $documentoId,
            'credenciais' => [
                'usuario' => $credencial['usuario'],
                'senha' => $credencial['senha'],
                'orgao_id' => $credencial['orgao_id'] ?? '31',
                'nome' => $user->nome_completo,
                'cargo' => $user->cargo,
            ],
        ];

        $credencial['senha'] = str_repeat("\0", strlen($credencial['senha']));
        unset($credencial);

        $response = $this->post('/api/documento/assinar', $payload);

        $this->logAction($user, 'assinar_documento_bloco', $documentoId, $response);

        return $response;
    }

    /**
     * Assina todos os documentos de um bloco.
     * 
     * @param User $user
     * @param string $blocoId
     * @return array
     */
    public function assinarBloco(User $user, string $blocoId): array
    {
        $credencial = $user->getCredencialSei();

        if (!$credencial) {
            return [
                'sucesso' => false,
                'erro' => 'Usuário não possui credencial SEI cadastrada',
            ];
        }

        $payload = [
            'usuario_sei' => $credencial['usuario'],
            'bloco_id' => $blocoId,
            'credenciais' => [
                'usuario' => $credencial['usuario'],
                'senha' => $credencial['senha'],
                'orgao_id' => $credencial['orgao_id'] ?? '31',
                'nome' => $user->nome_completo,
                'cargo' => $user->cargo,
            ],
        ];

        $credencial['senha'] = str_repeat("\0", strlen($credencial['senha']));
        unset($credencial);

        $response = $this->post('/api/bloco/assinar', $payload);

        $this->logAction($user, 'assinar_bloco', $blocoId, $response);

        return $response;
    }
}
