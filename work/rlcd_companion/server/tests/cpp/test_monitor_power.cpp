#include <assert.h>
#include "monitor_power.h"

int main() {
  using P=UsbStandbyPolicy;
  P p;
  assert(p.update(0,true,false,true,300)==P::None);
  p.update(10000,false,false,true,300);
  p.update(13000,false,false,true,300);
  assert(p.update(312999,false,false,true,300)==P::None);
  assert(p.update(313000,false,false,true,300)==P::EnterStandby);
  assert(p.sleeping);
  p.update(314000,true,false,true,300);
  assert(p.update(314250,true,false,true,300)==P::LeaveStandby);
  assert(!p.sleeping);

  P immediate;
  immediate.update(0,true,false,true,0);
  immediate.update(10000,false,false,true,0);
  assert(immediate.update(12999,false,false,true,0)==P::None);
  assert(immediate.update(13000,false,false,true,0)==P::EnterStandby);
  assert(immediate.update(14000,false,true,true,0)==P::LeaveStandby);
  assert(immediate.update(900000,false,false,true,0)==P::None); // manual hold
  immediate.update(900001,true,false,true,0);
  immediate.update(900251,true,false,true,0);
  immediate.update(900300,false,false,true,0);
  assert(immediate.update(903300,false,false,true,0)==P::EnterStandby);

  P disabled;
  disabled.update(0,false,false,false,0);
  assert(disabled.update(999999,false,false,false,0)==P::None);
  assert(!disabled.sleeping);

  P transient;
  transient.update(0,true,false,true,0);
  transient.update(10000,false,false,true,0);
  transient.update(12000,true,false,true,0);
  assert(transient.update(20000,true,false,true,0)==P::None);

  P boot;
  boot.update(0,false,false,true,0);
  assert(boot.update(3000,false,false,true,0)==P::None);
  assert(boot.update(10000,false,false,true,0)==P::EnterStandby);

  P wrap;
  wrap.update(0xffff0000u,true,false,true,5);
  wrap.update(0xfffff000u,false,false,true,5);
  wrap.update(0xfffffbb8u,false,false,true,5);
  assert(wrap.update(0x00000f40u,false,false,true,5)==P::EnterStandby);
  return 0;
}
