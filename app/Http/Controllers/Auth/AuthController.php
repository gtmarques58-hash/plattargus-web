<?php

namespace App\Http\Controllers\Auth;

use App\Http\Controllers\Controller;
use App\Models\User;
use App\Models\AuditLog;
use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\RateLimiter;

class AuthController extends Controller
{
    private int $maxAttempts = 5;
    private int $decayMinutes = 1;

    public function login(Request $request): JsonResponse
    {
        $request->validate([
            'usuario_sei' => 'required|string|max:100',
            'senha' => 'required|string',
        ]);

        $throttleKey = 'login:' . $request->ip() . ':' . strtolower($request->usuario_sei);
        
        if (RateLimiter::tooManyAttempts($throttleKey, $this->maxAttempts)) {
            $seconds = RateLimiter::availableIn($throttleKey);
            return response()->json([
                'success' => false,
                'message' => "Muitas tentativas. Aguarde {$seconds} segundos.",
                'retry_after' => $seconds,
            ], 429);
        }

        $usuarioSei = strtolower(trim($request->usuario_sei));
        $user = User::where('usuario_sei', $usuarioSei)->first();

        if (!$user || !Hash::check($request->senha, $user->password)) {
            RateLimiter::hit($throttleKey, $this->decayMinutes * 60);
            AuditLog::logLoginFailed($usuarioSei);
            return response()->json([
                'success' => false,
                'message' => 'Usuario ou senha invalidos.',
            ], 401);
        }

        if (!$user->ativo) {
            AuditLog::log($user->id, 'login_blocked', 'failure', null, null, [
                'reason' => 'user_inactive',
            ]);
            return response()->json([
                'success' => false,
                'message' => 'Usuario desativado. Contate o administrador.',
            ], 403);
        }

        RateLimiter::clear($throttleKey);
        $user->registrarAcesso();
        
        $token = $user->createToken('plattargus')->plainTextToken;
        
        AuditLog::logLogin($user->id);

        return response()->json([
            'success' => true,
            'message' => 'Login realizado com sucesso.',
            'token' => $token,
            'usuario' => [
                'id' => $user->id,
                'usuario_sei' => $user->usuario_sei,
                'nome_completo' => $user->nome_completo,
                'nome_exibicao' => $user->nome_exibicao,
                'posto_grad' => $user->posto_grad,
                'cargo' => $user->cargo,
                'unidade' => $user->unidade,
                'primeiro_acesso' => $user->primeiro_acesso,
                'tem_credencial_sei' => $user->hasCredencialSei(),
            ],
        ]);
    }

    public function primeiroAcesso(Request $request): JsonResponse
    {
        $request->validate([
            'usuario_sei' => 'required|string|max:100',
            'senha' => 'required|string|min:6|confirmed',
        ]);

        $usuarioSei = strtolower(trim($request->usuario_sei));
        $user = User::where('usuario_sei', $usuarioSei)->first();

        if (!$user) {
            return response()->json([
                'success' => false,
                'message' => 'Usuario nao encontrado. Voce precisa ser pre-cadastrado pelo administrador.',
            ], 404);
        }

        if (!$user->primeiro_acesso) {
            return response()->json([
                'success' => false,
                'message' => 'Voce ja definiu sua senha. Use o login normal.',
            ], 400);
        }

        $user->password = Hash::make($request->senha);
        $user->primeiro_acesso = false;
        $user->save();

        AuditLog::log($user->id, 'primeiro_acesso', 'success');

        return response()->json([
            'success' => true,
            'message' => 'Senha definida com sucesso! Faca login agora.',
        ]);
    }

    public function verificar(Request $request): JsonResponse
    {
        $user = $request->user();

        if (!$user) {
            return response()->json(['valid' => false]);
        }

        return response()->json([
            'valid' => true,
            'usuario' => [
                'id' => $user->id,
                'usuario_sei' => $user->usuario_sei,
                'nome_completo' => $user->nome_completo,
                'nome_exibicao' => $user->nome_exibicao,
                'posto_grad' => $user->posto_grad,
                'cargo' => $user->cargo,
                'unidade' => $user->unidade,
                'tem_credencial_sei' => $user->hasCredencialSei(),
            ],
        ]);
    }

    public function logout(Request $request): JsonResponse
    {
        $user = $request->user();
        
        if ($user) {
            AuditLog::logLogout($user->id);
            $user->currentAccessToken()->delete();
        }

        return response()->json([
            'success' => true,
            'message' => 'Logout realizado.',
        ]);
    }

    public function alterarSenha(Request $request): JsonResponse
    {
        $request->validate([
            'senha_atual' => 'required|string',
            'senha_nova' => 'required|string|min:6|confirmed',
        ]);

        $user = $request->user();

        if (!Hash::check($request->senha_atual, $user->password)) {
            return response()->json([
                'success' => false,
                'message' => 'Senha atual incorreta.',
            ], 400);
        }

        $user->password = Hash::make($request->senha_nova);
        $user->save();

        $user->tokens()->delete();

        AuditLog::log($user->id, 'alterar_senha', 'success');

        return response()->json([
            'success' => true,
            'message' => 'Senha alterada com sucesso.',
        ]);
    }

    public function me(Request $request): JsonResponse
    {
        $user = $request->user();

        return response()->json([
            'id' => $user->id,
            'usuario_sei' => $user->usuario_sei,
            'nome_completo' => $user->nome_completo,
            'nome_exibicao' => $user->nome_exibicao,
            'posto_grad' => $user->posto_grad,
            'cargo' => $user->cargo,
            'unidade' => $user->unidade,
            'email' => $user->email,
            'tem_credencial_sei' => $user->hasCredencialSei(),
            'sei_cargo' => $user->sei_cargo,
            'ativo' => $user->ativo,
            'ultimo_acesso' => $user->ultimo_acesso?->toIso8601String(),
            'criado_em' => $user->created_at->toIso8601String(),
        ]);
    }
}
