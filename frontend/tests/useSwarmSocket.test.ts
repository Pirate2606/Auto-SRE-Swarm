import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useSwarmSocket } from '../hooks/useSwarmSocket';

describe('useSwarmSocket', () => {
  let mockWebSocket: any;

  beforeEach(() => {
    mockWebSocket = {
      send: vi.fn(),
      close: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      readyState: 1 // OPEN
    };
    global.WebSocket = vi.fn(() => mockWebSocket) as any;
  });

  it('initial state is correct', () => {
    const { result } = renderHook(() => useSwarmSocket('inc-001'));
    
    expect(result.current.state.connectionStatus).toBe('connecting');
    expect(result.current.state.findings).toEqual([]);
    expect(result.current.state.conflicts).toEqual([]);
    expect(result.current.state.consensus).toBeNull();
  });

  it('agent_finding event updates state.findings', () => {
    const { result } = renderHook(() => useSwarmSocket('inc-001'));
    
    act(() => {
      mockWebSocket.onopen();
      mockWebSocket.onmessage({
        data: JSON.stringify({
          event: 'finding_added',
          payload: { id: 'f1', summary: 'test finding' }
        })
      });
    });

    expect(result.current.state.findings).toHaveLength(1);
    expect(result.current.state.findings[0].summary).toBe('test finding');
  });

  it('conflict_detected event updates state.conflicts', () => {
    const { result } = renderHook(() => useSwarmSocket('inc-001'));
    
    act(() => {
      mockWebSocket.onmessage({
        data: JSON.stringify({
          event: 'conflict_detected',
          payload: { id: 'c1', agent_a: 'log_forensics' }
        })
      });
    });

    expect(result.current.state.conflicts).toHaveLength(1);
    expect(result.current.state.conflicts[0].id).toBe('c1');
  });

  it('consensus_reached clears conflicts, sets consensus', () => {
    const { result } = renderHook(() => useSwarmSocket('inc-001'));
    
    // Add conflict first
    act(() => {
      mockWebSocket.onmessage({
        data: JSON.stringify({ event: 'conflict_detected', payload: { id: 'c1' } })
      });
    });
    
    // Trigger consensus
    act(() => {
      mockWebSocket.onmessage({
        data: JSON.stringify({
          event: 'consensus_reached',
          payload: { confidence: 0.9, hypothesis: { title: 'Test' } }
        })
      });
    });

    expect(result.current.state.conflicts).toHaveLength(0);
    expect(result.current.state.consensus?.confidence).toBe(0.9);
  });

  it('approval_required populates pendingApprovals', () => {
    const { result } = renderHook(() => useSwarmSocket('inc-001'));
    
    act(() => {
      mockWebSocket.onmessage({
        data: JSON.stringify({
          event: 'approval_requested',
          payload: { id: 'app1', action: { title: 'Restart' } }
        })
      });
    });

    expect(result.current.state.pendingApprovals).toHaveLength(1);
    expect(result.current.state.pendingApprovals[0].id).toBe('app1');
  });

  it('reconnection is attempted after disconnect', () => {
    vi.useFakeTimers();
    renderHook(() => useSwarmSocket('inc-001'));
    
    expect(global.WebSocket).toHaveBeenCalledTimes(1);
    
    act(() => {
      mockWebSocket.onclose();
    });
    
    act(() => {
      vi.advanceTimersByTime(1500); // Backoff starts at 1s
    });
    
    expect(global.WebSocket).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it('sendApprovalResponse sends correct JSON', () => {
    const { result } = renderHook(() => useSwarmSocket('inc-001'));
    
    act(() => {
      result.current.sendApprovalResponse('act-1', true, 'Looks good');
    });
    
    expect(mockWebSocket.send).toHaveBeenCalledWith(
      JSON.stringify({
        event: 'approval_response',
        payload: { action_id: 'act-1', approved: true, note: 'Looks good' }
      })
    );
  });
});
