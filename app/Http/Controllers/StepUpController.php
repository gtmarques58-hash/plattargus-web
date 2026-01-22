<?php

namespace App\Http\Controllers;

use App\Services\StepUpService;
use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;

class StepUpController extends Controller
{
    public function __construct(
        private StepUpService $stepUp
    ) {}

    /**
     * Solicita autorização step-up para ação crítica.
     * 
     * POST /api/step-up/grant
     */
    public function grant(Request $request): JsonResponse
    {
        $request->validate([
            'senha' => 'required|string',
            'action' => 'required|string|in:sign,sign_block,insert_sei,revoke_credential',
            'target_id' => 'required|string|max:100',
        ]);

        $user = $request->user();

        $result = $this->stepUp->requestGrant(
            user: $user,
            password: $request->senha,
            action: $request->action,
            targetId: $request->target_id,
            ip: $request->ip()
        );

        $statusCode = $result['success'] ? 200 : 401;
        
        if (isset($result['locked_until'])) {
            $statusCode = 429;
        }

        return response()->json($result, $statusCode);
    }

    /**
     * Verifica se existe grant válido.
     * 
     * POST /api/step-up/verify
     */
    public function verify(Request $request): JsonResponse
    {
        $request->validate([
            'action' => 'required|string',
            'target_id' => 'required|string',
        ]);

        $user = $request->user();

        $hasGrant = $this->stepUp->hasValidGrant(
            user: $user,
            action: $request->action,
            targetId: $request->target_id,
            ip: $request->ip()
        );

        return response()->json([
            'valid' => $hasGrant,
        ]);
    }

    /**
     * Lista grants ativos do usuário (debug/admin).
     * 
     * GET /api/step-up/active
     */
    public function active(Request $request): JsonResponse
    {
        $user = $request->user();

        return response()->json([
            'grants' => $this->stepUp->getActiveGrants($user->id),
        ]);
    }

    /**
     * Invalida todos os grants do usuário.
     * 
     * DELETE /api/step-up/invalidate
     */
    public function invalidate(Request $request): JsonResponse
    {
        $user = $request->user();

        $count = $this->stepUp->invalidateAllGrants($user->id);

        return response()->json([
            'success' => true,
            'invalidated' => $count,
        ]);
    }
}
