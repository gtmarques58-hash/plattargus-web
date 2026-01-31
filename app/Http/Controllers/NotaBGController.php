<?php

namespace App\Http\Controllers;

use App\Services\PlattEngineService;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;

/**
 * NotaBGController - Notas para Boletim Geral
 *
 * Endpoints para inserção de Notas BG no SEI.
 * A geração da nota é feita no FastAPI, a inserção aqui.
 */
class NotaBGController extends Controller
{
    private PlattEngineService $engine;

    // Tipo de documento no SEI
    private const TIPO_DOCUMENTO = 'Nota para Boletim Geral - BG - CBMAC';

    public function __construct(PlattEngineService $engine)
    {
        $this->engine = $engine;
    }

    /**
     * POST /api/nota-bg/inserir
     *
     * Insere uma Nota BG no SEI.
     *
     * Body:
     *   - nup: string (NUP do processo)
     *   - html: string (HTML da nota gerada)
     */
    public function inserir(Request $request)
    {
        $request->validate([
            'nup' => 'required|string',
            'html' => 'required|string',
        ]);

        $user = $request->user();

        if (!$user->sei_credencial_ativa) {
            return response()->json([
                'sucesso' => false,
                'erro' => 'Você precisa cadastrar sua credencial SEI primeiro.',
            ], 400);
        }

        $nup = $request->input('nup');
        $html = $request->input('html');

        Log::info('NotaBG inserir', [
            'user' => $user->usuario_sei,
            'nup' => $nup,
        ]);

        try {
            $resultado = $this->engine->inserirNoSei(
                $user,
                $nup,
                self::TIPO_DOCUMENTO,
                $html,
                null // destinatário
            );

            if ($resultado['sucesso'] ?? false) {
                return response()->json([
                    'sucesso' => true,
                    'nup' => $nup,
                    'tipo_documento' => self::TIPO_DOCUMENTO,
                    'numero_sei' => $resultado['numero_sei'] ?? $resultado['sei_numero'] ?? null,
                    'sei_numero' => $resultado['numero_sei'] ?? $resultado['sei_numero'] ?? null,
                    'mensagem' => 'Nota BG inserida no SEI com sucesso!',
                ]);
            }

            return response()->json([
                'sucesso' => false,
                'erro' => $resultado['erro'] ?? 'Erro ao inserir no SEI',
            ], 500);

        } catch (\Exception $e) {
            Log::error('NotaBG inserir erro', [
                'user' => $user->usuario_sei,
                'nup' => $nup,
                'error' => $e->getMessage(),
            ]);

            return response()->json([
                'sucesso' => false,
                'erro' => 'Erro interno: ' . $e->getMessage(),
            ], 500);
        }
    }
}
