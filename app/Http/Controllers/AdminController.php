<?php

namespace App\Http\Controllers;

use App\Models\User;
use App\Models\AuditLog;
use App\Models\ProcessAnalysis;
use App\Models\GeneratedDocument;
use App\Services\PlattEngineService;
use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Str;

class AdminController extends Controller
{
    public function __construct(
        private PlattEngineService $engine
    ) {}

    // =========================================================================
    // GERENCIAMENTO DE USUÁRIOS
    // =========================================================================

    /**
     * Lista todos os usuários.
     * 
     * GET /api/admin/usuarios
     */
    public function listarUsuarios(Request $request): JsonResponse
    {
        $query = User::query();

        // Filtros
        if ($request->has('ativo')) {
            $query->where('ativo', $request->boolean('ativo'));
        }

        if ($request->has('unidade')) {
            $query->where('unidade', $request->unidade);
        }

        if ($request->has('search')) {
            $search = $request->search;
            $query->where(function ($q) use ($search) {
                $q->where('usuario_sei', 'like', "%{$search}%")
                  ->orWhere('nome_completo', 'like', "%{$search}%");
            });
        }

        $usuarios = $query->orderBy('nome_completo')
            ->get([
                'id', 'usuario_sei', 'matricula', 'nome_completo', 'posto_grad',
                'cargo', 'unidade', 'ativo', 'primeiro_acesso',
                'sei_credencial_ativa', 'ultimo_acesso', 'created_at'
            ]);

        return response()->json([
            'usuarios' => $usuarios,
            'total' => $usuarios->count(),
        ]);
    }

    /**
     * Cria novo usuário (pré-cadastro).
     * 
     * POST /api/admin/usuarios
     */
    public function criarUsuario(Request $request): JsonResponse
    {
        $request->validate([
            'usuario_sei' => 'required|string|max:100|unique:users,usuario_sei',
            'matricula' => 'nullable|string|max:20|unique:users,matricula',
            'nome_completo' => 'required|string|max:255',
            'posto_grad' => 'nullable|string|max:50',
            'cargo' => 'nullable|string|max:100',
            'unidade' => 'nullable|string|max:100',
            'email' => 'nullable|email|max:255',
        ]);

        // Senha temporária (usuário define no primeiro acesso)
        $senhaTemp = Str::random(32);

        $usuario = User::create([
            'usuario_sei' => strtolower(trim($request->usuario_sei)),
            'matricula' => $request->matricula,
            'password' => Hash::make($senhaTemp),
            'nome_completo' => $request->nome_completo,
            'posto_grad' => $request->posto_grad,
            'cargo' => $request->cargo,
            'unidade' => $request->unidade,
            'email' => $request->email,
            'ativo' => true,
            'primeiro_acesso' => true,
        ]);

        AuditLog::log(
            $request->user()->id,
            'admin_create_user',
            'success',
            'user',
            $usuario->usuario_sei
        );

        return response()->json([
            'success' => true,
            'message' => 'Usuário criado. Deve definir senha no primeiro acesso.',
            'usuario' => [
                'id' => $usuario->id,
                'usuario_sei' => $usuario->usuario_sei,
                'nome_completo' => $usuario->nome_completo,
            ],
        ], 201);
    }

    /**
     * Atualiza dados do usuário.
     * 
     * PUT /api/admin/usuarios/{id}
     */
    public function atualizarUsuario(Request $request, int $id): JsonResponse
    {
        $usuario = User::findOrFail($id);

        $request->validate([
            'nome_completo' => 'nullable|string|max:255',
            'posto_grad' => 'nullable|string|max:50',
            'cargo' => 'nullable|string|max:100',
            'unidade' => 'nullable|string|max:100',
            'email' => 'nullable|email|max:255',
        ]);

        $usuario->update($request->only([
            'nome_completo', 'posto_grad', 'cargo', 'unidade', 'email'
        ]));

        AuditLog::log(
            $request->user()->id,
            'admin_update_user',
            'success',
            'user',
            $usuario->usuario_sei
        );

        return response()->json([
            'success' => true,
            'message' => 'Usuário atualizado.',
        ]);
    }

    /**
     * Desativa usuário (soft delete).
     * 
     * DELETE /api/admin/usuarios/{id}
     */
    public function desativarUsuario(Request $request, int $id): JsonResponse
    {
        $usuario = User::findOrFail($id);

        // Não pode desativar a si mesmo
        if ($usuario->id === $request->user()->id) {
            return response()->json([
                'success' => false,
                'message' => 'Você não pode desativar a si mesmo.',
            ], 400);
        }

        $usuario->ativo = false;
        $usuario->save();

        // Revoga tokens
        $usuario->tokens()->delete();

        AuditLog::log(
            $request->user()->id,
            'admin_deactivate_user',
            'success',
            'user',
            $usuario->usuario_sei
        );

        return response()->json([
            'success' => true,
            'message' => 'Usuário desativado.',
        ]);
    }

    /**
     * Reativa usuário.
     * 
     * POST /api/admin/usuarios/{id}/reativar
     */
    public function reativarUsuario(Request $request, int $id): JsonResponse
    {
        $usuario = User::findOrFail($id);
        
        $usuario->ativo = true;
        $usuario->save();

        AuditLog::log(
            $request->user()->id,
            'admin_reactivate_user',
            'success',
            'user',
            $usuario->usuario_sei
        );

        return response()->json([
            'success' => true,
            'message' => 'Usuário reativado.',
        ]);
    }

    /**
     * Reseta senha do usuário (volta para primeiro acesso).
     * 
     * POST /api/admin/usuarios/{id}/reset-senha
     */
    public function resetSenha(Request $request, int $id): JsonResponse
    {
        $usuario = User::findOrFail($id);

        // Nova senha temporária
        $senhaTemp = Str::random(32);
        
        $usuario->password = Hash::make($senhaTemp);
        $usuario->primeiro_acesso = true;
        $usuario->save();

        // Revoga tokens
        $usuario->tokens()->delete();

        AuditLog::log(
            $request->user()->id,
            'admin_reset_password',
            'success',
            'user',
            $usuario->usuario_sei
        );

        return response()->json([
            'success' => true,
            'message' => 'Senha resetada. Usuário deve definir nova senha no próximo acesso.',
        ]);
    }

    // =========================================================================
    // AUDITORIA
    // =========================================================================

    /**
     * Lista logs de auditoria.
     * 
     * GET /api/admin/auditoria
     */
    public function auditoria(Request $request): JsonResponse
    {
        $query = AuditLog::with('user:id,usuario_sei,nome_completo');

        // Filtros
        if ($request->has('action')) {
            $query->where('action', $request->action);
        }

        if ($request->has('status')) {
            $query->where('status', $request->status);
        }

        if ($request->has('user_id')) {
            $query->where('user_id', $request->user_id);
        }

        if ($request->has('data_inicio')) {
            $query->where('created_at', '>=', $request->data_inicio);
        }

        if ($request->has('data_fim')) {
            $query->where('created_at', '<=', $request->data_fim);
        }

        $logs = $query->orderBy('created_at', 'desc')
            ->limit($request->limit ?? 100)
            ->get();

        return response()->json([
            'logs' => $logs,
        ]);
    }

    /**
     * Logs de auditoria de um usuário específico.
     * 
     * GET /api/admin/auditoria/usuario/{id}
     */
    public function auditoriaUsuario(Request $request, int $id): JsonResponse
    {
        $logs = AuditLog::where('user_id', $id)
            ->orderBy('created_at', 'desc')
            ->limit($request->limit ?? 50)
            ->get();

        return response()->json([
            'logs' => $logs,
        ]);
    }

    // =========================================================================
    // ESTATÍSTICAS
    // =========================================================================

    /**
     * Estatísticas gerais do sistema.
     * 
     * GET /api/admin/estatisticas
     */
    public function estatisticas(): JsonResponse
    {
        return response()->json([
            'usuarios' => [
                'total' => User::count(),
                'ativos' => User::where('ativo', true)->count(),
                'com_credencial' => User::where('sei_credencial_ativa', true)->count(),
                'primeiro_acesso_pendente' => User::where('primeiro_acesso', true)->count(),
            ],
            'processos' => [
                'analises_total' => ProcessAnalysis::count(),
                'analises_hoje' => ProcessAnalysis::whereDate('created_at', today())->count(),
                'analises_semana' => ProcessAnalysis::where('created_at', '>=', now()->subWeek())->count(),
            ],
            'documentos' => [
                'gerados_total' => GeneratedDocument::count(),
                'inseridos_sei' => GeneratedDocument::where('inserido_sei', true)->count(),
                'assinados' => GeneratedDocument::where('assinado', true)->count(),
            ],
            'auditoria' => [
                'logins_hoje' => AuditLog::where('action', 'login')
                    ->whereDate('created_at', today())->count(),
                'assinaturas_hoje' => AuditLog::where('action', 'sign_document')
                    ->whereDate('created_at', today())->count(),
                'falhas_hoje' => AuditLog::where('status', 'failure')
                    ->whereDate('created_at', today())->count(),
            ],
            'por_unidade' => User::where('ativo', true)
                ->groupBy('unidade')
                ->selectRaw('unidade, count(*) as total')
                ->pluck('total', 'unidade'),
        ]);
    }

    // =========================================================================
    // ENGINE
    // =========================================================================

    /**
     * Verifica saúde do Engine.
     * 
     * GET /api/admin/engine/health
     */
    public function engineHealth(): JsonResponse
    {
        $health = $this->engine->healthCheck();

        return response()->json($health);
    }
}
