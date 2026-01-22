<?php

namespace App\Http\Controllers;

use App\Models\AuditLog;
use App\Services\CredentialVaultService;
use App\Services\PlattEngineService;
use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;

class CredentialController extends Controller
{
    public function __construct(
        private CredentialVaultService $vault,
        private PlattEngineService $engine
    ) {}

    /**
     * Verifica se o usuário tem credencial SEI cadastrada.
     * 
     * GET /api/credencial/status
     */
    public function status(Request $request): JsonResponse
    {
        $user = $request->user();

        return response()->json([
            'tem_credencial' => $user->hasCredencialSei(),
            'sei_orgao_id' => $user->sei_orgao_id,
            'sei_cargo' => $user->sei_cargo,
            'usuario_sei' => $user->usuario_sei,
        ]);
    }

    /**
     * Cadastra ou atualiza credencial SEI.
     * 
     * POST /api/credencial/vincular
     */
    public function vincular(Request $request): JsonResponse
    {
        $request->validate([
            'senha_sei' => 'required|string|min:1',
            'orgao_id' => 'required|string|max:10',
            'cargo' => 'required|string|max:100',
            'testar_login' => 'boolean',
        ]);

        $user = $request->user();

        // Opcional: testar login antes de salvar
        if ($request->boolean('testar_login', false)) {
            $testeResult = $this->testarCredencial(
                $user->usuario_sei,
                $request->senha_sei,
                $request->orgao_id
            );

            if (!$testeResult['sucesso']) {
                return response()->json([
                    'success' => false,
                    'message' => 'Credencial inválida. Verifique usuário, senha e órgão.',
                    'detalhes' => $testeResult['erro'] ?? null,
                ], 400);
            }
        }

        try {
            // Criptografa e salva
            $user->setCredencialSei(
                $request->senha_sei,
                $request->orgao_id,
                $request->cargo
            );

            AuditLog::logCredentialCreate($user->id);

            return response()->json([
                'success' => true,
                'message' => 'Credencial SEI vinculada com sucesso!',
            ]);

        } catch (\Exception $e) {
            report($e);

            return response()->json([
                'success' => false,
                'message' => 'Erro ao salvar credencial. Tente novamente.',
            ], 500);
        }
    }

    /**
     * Remove credencial SEI.
     * 
     * DELETE /api/credencial
     */
    public function remover(Request $request): JsonResponse
    {
        $user = $request->user();

        if (!$user->hasCredencialSei()) {
            return response()->json([
                'success' => false,
                'message' => 'Nenhuma credencial para remover.',
            ], 400);
        }

        $user->removeCredencialSei();

        AuditLog::log($user->id, 'credential_remove', 'success');

        return response()->json([
            'success' => true,
            'message' => 'Credencial SEI removida.',
        ]);
    }

    /**
     * Atualiza apenas a senha SEI.
     * 
     * PUT /api/credencial/senha
     */
    public function atualizarSenha(Request $request): JsonResponse
    {
        $request->validate([
            'senha_sei' => 'required|string|min:1',
            'testar_login' => 'boolean',
        ]);

        $user = $request->user();

        // Opcional: testar login
        if ($request->boolean('testar_login', false)) {
            $testeResult = $this->testarCredencial(
                $user->usuario_sei,
                $request->senha_sei,
                $user->sei_orgao_id ?? '31'
            );

            if (!$testeResult['sucesso']) {
                return response()->json([
                    'success' => false,
                    'message' => 'Nova senha inválida.',
                    'detalhes' => $testeResult['erro'] ?? null,
                ], 400);
            }
        }

        try {
            // Criptografa nova senha
            $encrypted = $this->vault->encrypt($request->senha_sei);

            $user->sei_senha_cipher = $encrypted['ciphertext'];
            $user->sei_senha_iv = $encrypted['iv'];
            $user->sei_senha_tag = $encrypted['tag'];
            $user->sei_credencial_ativa = true;
            $user->save();

            AuditLog::log($user->id, 'credential_update', 'success');

            return response()->json([
                'success' => true,
                'message' => 'Senha SEI atualizada com sucesso!',
            ]);

        } catch (\Exception $e) {
            report($e);

            return response()->json([
                'success' => false,
                'message' => 'Erro ao atualizar senha.',
            ], 500);
        }
    }

    /**
     * Atualiza cargo para assinatura.
     * 
     * PUT /api/credencial/cargo
     */
    public function atualizarCargo(Request $request): JsonResponse
    {
        $request->validate([
            'cargo' => 'required|string|max:100',
        ]);

        $user = $request->user();
        $user->sei_cargo = $request->cargo;
        $user->save();

        return response()->json([
            'success' => true,
            'message' => 'Cargo atualizado.',
        ]);
    }

    /**
     * Testa credencial sem salvar.
     * 
     * POST /api/credencial/testar
     */
    public function testar(Request $request): JsonResponse
    {
        $request->validate([
            'senha_sei' => 'required|string',
            'orgao_id' => 'string|max:10',
        ]);

        $user = $request->user();
        
        $result = $this->testarCredencial(
            $user->usuario_sei,
            $request->senha_sei,
            $request->orgao_id ?? '31'
        );

        return response()->json([
            'success' => $result['sucesso'],
            'message' => $result['sucesso'] 
                ? 'Credencial válida!' 
                : 'Credencial inválida: ' . ($result['erro'] ?? 'erro desconhecido'),
            'tempo_login' => $result['tempo_login'] ?? null,
        ]);
    }

    /**
     * Lista órgãos disponíveis.
     * 
     * GET /api/credencial/orgaos
     */
    public function orgaos(): JsonResponse
    {
        // Por enquanto, lista estática. Pode ser dinâmica no futuro.
        return response()->json([
            'orgaos' => [
                ['id' => '31', 'nome' => 'CBMAC', 'descricao' => 'Corpo de Bombeiros Militar do Acre'],
                ['id' => '26', 'nome' => 'PMAC', 'descricao' => 'Polícia Militar do Acre'],
                // Adicionar outros órgãos conforme necessário
            ],
        ]);
    }

    /**
     * Lista cargos comuns para assinatura.
     * 
     * GET /api/credencial/cargos
     */
    public function cargos(): JsonResponse
    {
        return response()->json([
            'cargos' => [
                'Diretor(a)',
                'Chefe de Seção',
                'Comandante',
                'Subcomandante',
                'Analista Administrativo',
                'Assessor(a)',
                'Secretário(a)',
                'Técnico Administrativo',
                // Adicionar mais conforme necessário
            ],
        ]);
    }

    // =========================================================================
    // HELPERS PRIVADOS
    // =========================================================================

    /**
     * Testa credencial via Engine.
     */
    private function testarCredencial(string $usuario, string $senha, string $orgaoId): array
    {
        // TODO: Implementar chamada ao Engine para testar login
        // Por ora, retorna sucesso (implementar quando Engine estiver pronto)
        
        // Simulação:
        // return $this->engine->testarCredencial($usuario, $senha, $orgaoId);
        
        return [
            'sucesso' => true,
            'tempo_login' => 2.5,
        ];
    }
}
